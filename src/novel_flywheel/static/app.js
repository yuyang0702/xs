const state = { projects: [], trash: [], providers: [], skills: [], wizards: [], references: [], mechanisms: [], projectLearning:null, effectiveRules:null, outlines:null, activeOutlineCandidateId:null, outlineComparison:null, learningReport:null, attractionMap:null, referenceTask:null, referenceTaskTimer:null, localNlp:null, workflowAnalysis:null, market:null, marketBaselines:[], marketBaseline:null, marketMatch:null, importReceipt:null, publicationPreview:null, candidateQuality:null, candidateControls:null, activeReference: null, referenceContent: "", referenceAnalysis: null, activeProject: null, activeWizard: null, wizardStep: 0, wizardConfirmedMethods:null, wizardMethodsFor:null, selectedWizardMethods:new Set(), wizardSourceReferenceId:null, wizardAutoOutline:false, activeRun: null, pollTimer: null, interviewWizardId: null, interviewMessages: [], interviewBusy: false, editingProviderId: null, storyState: null, materials: null, activeCharacter: null, activeMaterialGroup:"characters", activeMaterialPath:null };
const genres = {
  "玄幻奇幻": ["东方玄幻", "西方奇幻", "仙侠", "魔法学院"],
  "科幻": ["硬科幻", "赛博朋克", "星际", "末世"],
  "悬疑": ["推理", "刑侦", "社会派", "惊悚"],
  "言情": ["现代言情", "古代言情", "青春恋爱", "婚恋"],
  "都市": ["都市生活", "商战", "娱乐圈", "异能"],
  "历史": ["架空历史", "历史正剧", "战争", "宫廷"],
  "武侠": ["传统武侠", "江湖恩仇", "新武侠"],
  "现实主义": ["家庭", "社会", "乡土", "成长"],
  "恐怖": ["民俗", "心理恐怖", "怪谈"],
  "青春": ["校园", "成长", "友情"],
  "职场": ["行业", "创业", "律政", "医疗"],
  "同人": ["影视同人", "动漫同人", "游戏同人"]
};
const roles = {
  planning: "开书与章节规划", draft: "正文粗稿", review: "逻辑与合规审核",
  reader_review: "目标读者模拟", polish: "精修与去 AI 味",
  reference_analysis: "参考资料分窗分析", reference_synthesis: "学习机制综合", line_edit: "定向行文精修",
  final_review: "独立终审", maintenance: "项目资料更新"
};
const workflowLabels = {
  "initialize-skills":"作品初始化", "short-story":"短篇完整创作", "long-setup":"长篇准备",
  "long-chapter":"长篇章节创作", "materials-audit":"资料检查", "materials-repair":"资料修复",
  archive:"归档", primary:"主模型", circuit_fallback:"备用模型"
};
const findingLabels = {
  timestamp_scene_fragment:"时间与场景切换过于模板化", epiphany_formula:"顿悟表达过于公式化",
  binary_formula:"“不是……而是……”句式重复", vague_metaphor:"比喻含义不够具体",
  emotion_explained:"直接解释情绪", weak_adverb_density:"弱化副词偏多",
  theme_summary_ending:"结尾概括主题过多", one_sentence_paragraph_run:"连续单句成段",
  uniform_short_sentence_run:"连续短句过于整齐", dialogue_ping_pong:"连续对话缺少动作和变化",
  production_text:"正文混入修改说明", checklist_judgment:"连续下结论，缺少过程",
  functional_repetition:"相邻段落作用重复", repeated_phrase:"短距离重复表达",
  mechanical_dialogue_run:"连续对话缺少场景动作", regular_sentence_rhythm:"句子节奏过于整齐",
  repeated_body_reaction:"身体反应重复", unsupported_certainty:"人物判断缺少证据",
  project_forbidden_pattern:"出现当前作品禁用表达"
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
const readableModelText = (value, fallback="模型返回的旧结果没有完成中文化，请重新运行模型全文分析。") => {
  const text=String(value??"").trim();
  return text&&/[\u3400-\u9fff]/.test(text)?text:fallback;
};
const runLabel = value => roles[value] || workflowLabels[value] || ({
  editorial:"编辑检查", target_reader:"目标读者检查", chief_editor:"主编终审", tool_use:"工具调用",
  token_budget_exhausted:"模型用量已到上限"
}[value]) || (/[㐀-鿿]/.test(String(value||"")) ? String(value) : (String(value || "").trim() ? "系统阶段" : "未记录"));
const findingLabel = value => {
  const text=String(value||"").trim();
  const numbered=text.match(/^issue[_-]?(\d+)$/i);
  return findingLabels[text] || (numbered ? `问题 ${numbered[1]}` : (/[㐀-鿿]/.test(text) ? text : "系统检查项"));
};
const platformLabel = value => ({zhihu:"知乎",fanqie:"番茄",wechat:"公众号",jinjiang:"晋江"}[value] || value || "未识别平台");
const lengthTypeLabel = value => ({short:"短篇",long:"长篇",unknown:"未判断篇幅",all:"全部篇幅"}[value] || value || "未判断篇幅");
const readableRunMessage = value => {
  const text=String(value||"").trim();
  if(!text)return "未返回可用说明";
  const errorCode=text.match(/\b([45]\d\d)\b/)?.[1];
  if(/(?:Server|Client) error|disconnected|Timeout|timed out/i.test(text)) {
    if(errorCode==="404")return "模型接口地址不存在（错误码 404），请检查供应商地址和接口类型。";
    if(errorCode==="524")return "模型服务响应超时（错误码 524），已有进度已保留，可以继续运行。";
    return `模型服务连接失败${errorCode?`（错误码 ${errorCode}）`:""}，已有进度已保留。`;
  }
  if(/model returned empty output/i.test(text))return "模型没有返回可用正文，已有进度已保留，可以继续运行。";
  const exact = {
    "Polish request context sized before provider call":"已整理本次精修所需内容",
    "Polish input token budget exhausted; stopped before the next model call":"精修模型用量已到上限，已在下一次调用前停止",
    "Quality revision stopped and preserved the best candidate":"返修已停止，当前最佳候选稿已保留",
    "Quality revision halted; preserved best candidate (token_budget_exhausted)":"返修因模型用量到达上限而停止，当前最佳候选稿已保留",
    "Server disconnected without sending a response.":"模型服务断开连接，没有返回内容；已有进度已保留。"
  };
  if(exact[text])return exact[text];
  let result=text
    .replace(/已加载 (\d+) 个 Skill/g,"已加载 $1 项写作能力")
    .replace(/\bplanning\b/g,"规划")
    .replace(/\breader_review\b/g,"目标读者检查")
    .replace(/\bfinal_review\b/g,"独立终审")
    .replace(/\breview\b/g,"审稿")
    .replace(/\bpolish\b/gi,"精修")
    .replace(/\bmaintenance\b/g,"资料更新")
    .replace(/\beditorial\b/g,"编辑检查")
    .replace(/\btarget_reader\b/g,"目标读者检查")
    .replace(/\bchief_editor\b/g,"主编终审")
    .replace(/\bcircuit_fallback\b/g,"备用模型")
    .replace(/\bprimary\b/g,"主模型")
    .replace(/\barchive\b/g,"归档")
    .replace(/\btoken_budget_exhausted\b/g,"模型用量已到上限")
    .replace(/\btool_use\b/g,"工具调用");
  return /[A-Za-z]/.test(result) && !/[㐀-鿿]/.test(result)
    ? "系统记录了一条技术信息；如任务失败，请在模型设置中检查连接后继续运行。"
    : result.replace(/https?:\/\/\S+/g,"").trim();
};
const formatLocalTimestamp = (value, timeOnly = false) => {
  const text = String(value ?? "").trim();
  if (!text) return "";
  const normalized = text.includes("T") ? text : text.replace(" ", "T");
  const hasZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(normalized);
  const date = new Date(hasZone ? normalized : `${normalized}Z`);
  if (Number.isNaN(date.getTime())) return text;
  const options = timeOnly
    ? {hour12:false, hour:"2-digit", minute:"2-digit", second:"2-digit"}
    : {hour12:false, year:"numeric", month:"2-digit", day:"2-digit", hour:"2-digit", minute:"2-digit", second:"2-digit"};
  return timeOnly ? date.toLocaleTimeString("zh-CN", options) : date.toLocaleString("zh-CN", options);
};
const isQualityRejected = run => run.status === "failed" && String(run.error || "").includes("quality gate");
const runStatusLabel = run => isQualityRejected(run) ? "质量未通过" : ({
  queued:"排队中", running:"执行中", cancelling:"终止中", completed:"已完成",
  cancelled:"已终止", failed:"失败"
}[run.status] || run.status);

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(typeof body.detail === "string" ? body.detail : (body.detail?.message || body.detail?.code || `HTTP ${response.status}`));
  }
  if (response.status === 204) return null;
  return response.json();
}
function toast(message) { const el = $("#toast"); el.textContent = message; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2600); }

function showView(name, label) {
  document.querySelectorAll(".nav-item,.view").forEach(el => el.classList.remove("active"));
  const nav = document.querySelector(`.nav-item[data-view="${name}"]`); if (nav) nav.classList.add("active");
  $(`#${name}`).classList.add("active"); $("#view-title").textContent = label || nav?.textContent || "小说飞轮";
}
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", async () => {
  showView(button.dataset.view, button.textContent);
  if (button.dataset.view === "materials") await renderMaterials();
  if (button.dataset.view === "market") await loadMarketDashboard();
}));
document.querySelectorAll("[data-view-target]").forEach(button => button.addEventListener("click", () => showView(button.dataset.viewTarget)));

async function loadAll() {
  [state.projects, state.trash, state.providers, state.skills, state.wizards, state.references, state.mechanisms, state.localNlp, state.marketBaselines] = await Promise.all([api("/api/projects"), api("/api/projects/trash"), api("/api/providers"), api("/api/skills"), api("/api/wizards"), api("/api/references"), api("/api/learning/mechanisms"), api("/api/settings/local-nlp"), api("/api/market/baselines")]);
  renderProjects(); renderTrash(); renderProviders(); renderSkills(); renderBindings(); renderWizardDrafts(); renderReferences(); renderLearning(); renderNlpStatus();
}

function renderReferences() {
  const list = $("#reference-list");
  const typeLabels={reference_work:"参考作品",platform_rule:"平台规则",popular_sample:"爆款样本",writing_tutorial:"写作教程",competitor_work:"竞品作品"};
  const projectOptions=state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("");
  if ($("#reference-project")) $("#reference-project").innerHTML='<option value="">不关联作品</option>'+projectOptions;
  if ($("#reference-filter-project")) {
    const selected=$("#reference-filter-project").value;
    $("#reference-filter-project").innerHTML='<option value="">全部作品</option><option value="unlinked">未关联作品</option>'+projectOptions;
    $("#reference-filter-project").value=selected;
  }
  if ($("#reference-filter-platform")) {
    const selected=$("#reference-filter-platform").value;
    const platforms=[...new Set(state.references.map(item=>item.platform).filter(Boolean))];
    $("#reference-filter-platform").innerHTML='<option value="">全部平台</option>'+platforms.map(item=>`<option>${escapeHtml(item)}</option>`).join("");
    $("#reference-filter-platform").value=selected;
  }
  if (!state.references.length) {
    state.activeReference = null;
    list.innerHTML = '<p class="skill-meta reference-empty">尚未导入参考资料</p>';
    $("#reference-detail").innerHTML = '<p class="skill-meta">选择参考资料后查看原文和本地诊断</p>';
    return;
  }
  if (!state.activeReference || !state.references.some(item => item.id === state.activeReference.id)) {
    state.activeReference = state.references[0];
  }
  const keyword=($("#reference-search")?.value||"").trim().toLowerCase();
  const platform=$("#reference-filter-platform")?.value||"";
  const contentType=$("#reference-filter-type")?.value||"";
  const project=$("#reference-filter-project")?.value||"";
  const filtered=state.references.filter(item=>{
    const haystack=`${item.title} ${item.platform||""} ${typeLabels[item.content_type]||""}`.toLowerCase();
    return (!keyword||haystack.includes(keyword))&&(!platform||item.platform===platform)&&(!contentType||item.content_type===contentType)&&(!project||(project==="unlinked"?!item.project_id:item.project_id===project));
  });
  list.innerHTML = filtered.length ? filtered.map(item => {
    const linked=state.projects.find(project=>project.id===item.project_id);
    return `<button class="reference-list-item ${item.id === state.activeReference.id ? "active" : ""}" data-reference-id="${item.id}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(platformLabel(item.platform||"未指定平台"))} · ${escapeHtml(typeLabels[item.content_type]||"参考作品")}${linked?` · 关联《${escapeHtml(linked.title)}》`:""}</span><span>${Number(item.latest_version?.character_count || 0).toLocaleString()} 字符 · ${item.versions.length} 个版本</span></button>`;
  }).join("") : '<p class="skill-meta reference-empty">没有符合筛选条件的资料</p>';
  list.querySelectorAll("[data-reference-id]").forEach(button => button.addEventListener("click", () => selectReference(button.dataset.referenceId)));
  if (!state.referenceContent) loadReferenceContent(state.activeReference.id);
  else renderReferenceDetail();
}

async function selectReference(sourceId) {
  const source = state.references.find(item => item.id === sourceId);
  if (!source) return;
  state.activeReference = source;
  state.referenceAnalysis = null;
  state.learningReport = null;
  state.attractionMap = null;
  state.referenceTask = null;
  clearTimeout(state.referenceTaskTimer);
  state.referenceContent = "";
  renderReferences();
  loadReferenceAnalysisTask(sourceId);
}

function renderImportReceipt() {
  const shell=$("#reference-import-receipt"), receipt=state.importReceipt;
  if(!shell)return;
  if(!receipt){shell.hidden=true;shell.innerHTML="";return;}
  shell.hidden=false;
  const list=items=>items?.length?`<ul>${items.map(item=>`<li>${escapeHtml(item)}</li>`).join("")}</ul>`:'<p>暂无</p>';
  const actions=(receipt.next_steps||[]).map((item,index)=>`<button type="button" class="${index===0?"primary receipt-primary-action":"secondary"}" data-receipt-action="${escapeHtml(item.action)}">${escapeHtml(item.label)}</button>`).join("");
  shell.innerHTML=`<header><div><span>资料已保存</span><h3>${escapeHtml(receipt.headline)}</h3></div><strong>${escapeHtml(receipt.trust_label)}</strong></header><section class="receipt-purpose"><span>系统判断</span><p>${escapeHtml(receipt.market_message)}</p><strong>可以用于</strong>${list(receipt.recommended_for)}</section><details class="receipt-details"><summary>查看判断依据和使用范围</summary><div class="receipt-grid"><section><span>判断依据</span>${list(receipt.reasons)}</section><section><span>不会用于</span>${list(receipt.not_used_for)}</section></div></details><footer><div><span>下一步</span><p>${escapeHtml(receipt.cost_message)}</p></div><div>${actions}</div></footer>`;
  shell.querySelectorAll("[data-receipt-action]").forEach(button=>button.addEventListener("click",()=>runReceiptAction(button.dataset.receiptAction)));
}

async function runReceiptAction(action){
  if(!state.activeReference)return;
  if(action==="market_match")return matchReferenceMarket(state.activeReference.id);
  if(action==="local_learn")return learnReference();
  if(action==="local_analyze")return analyzeReference();
  if(action==="popular_analysis")return analyzePopularReference();
}

async function loadReferenceContent(sourceId) {
  $("#reference-detail").innerHTML = '<p class="skill-meta">正在读取本地原文...</p>';
  try {
    const content = await api(`/api/references/${sourceId}/content`);
    if (state.activeReference?.id !== sourceId) return;
    state.referenceContent = content.text;
    state.attractionMap = await api(`/api/references/${sourceId}/attraction-map`);
    renderReferenceDetail();
    loadReferenceAnalysisTask(sourceId);
  } catch(error) { toast(error.message); }
}

function diagnosticCopy(item) {
  const impacts={
    unsupported_certainty:"读者还没有看到足够依据，人物却已经下定结论，容易让判断显得像作者直接宣布。",
    repeated_phrase:"短距离重复相同表达会让读者感觉文字停在原地；如果是有意循环，需要让第二次出现承担新的信息。",
    mechanical_dialogue_run:"连续问答如果缺少动作、观察或关系变化，人物容易像在交换资料，而不是身处真实场景。",
    regular_sentence_rhythm:"连续句子长度和结构太接近，阅读节奏会变得机械，紧张和舒缓也不容易区分。",
    one_sentence_paragraph_run:"连续使用短小单句段落会削弱真正需要强调的位置，让页面节奏显得碎。",
    repeated_body_reaction:"不同情绪反复使用同一种身体反应，会让人物感受变得单一。",
    project_forbidden_pattern:"这处表达碰到了当前作品已经明确设定的禁用规则。",
  };
  return {
    problem:item.message||"这里可能需要你复核",
    impact:impacts[item.rule_id]||"这条本地规则发现了可能影响理解或节奏的位置，需要结合上下文由你最终判断。",
    action:item.repair_goal||"检查这段是否让读者获得了足够信息，并决定保留或修改。",
  };
}

function renderDiagnosticFinding(item) {
  const copy=diagnosticCopy(item);
  const excerpt=String(item.evidence||"");
  return `<article class="diagnostic-card"><section><span>发现了什么</span><strong>${escapeHtml(copy.problem)}</strong></section><section><span>为什么可能影响阅读</span><p>${escapeHtml(copy.impact)}</p></section><section><span>建议你检查什么</span><p>${escapeHtml(copy.action)}</p></section><section><span>原文证据</span><blockquote>${escapeHtml(excerpt.length>360?excerpt.slice(0,360)+"…":excerpt)}</blockquote>${excerpt.length>360?`<details><summary>查看完整原文证据</summary><blockquote>${escapeHtml(excerpt)}</blockquote></details>`:""}</section><details class="diagnostic-technical"><summary>技术详情</summary><p>规则：${escapeHtml(item.rule_id)} · 级别：${escapeHtml(item.severity)}</p></details></article>`;
}

function referenceTaskMarkup() {
  const task=state.referenceTask;
  if(!task||task.status==="idle")return `<div><strong>分析状态</strong><p>选择本地诊断、本地提炼或模型全文分析后，这里会持续显示进度和结果。</p></div>`;
  const labels={queued:"等待分析",running:"正在分析",completed:"分析完成",failed:"分析失败",cancelled:"已停止"};
  const phases={starting:"正在准备全文",analyzing_windows:"正在逐段分析全文",fallback_window:"首选模型结果无效，正在使用已配置的备用模型分析当前窗口",synthesizing:"正在合并全文结论",fallback_synthesis:"首选模型汇总结果无效，正在使用已配置的备用模型汇总",completed:"结果已经生成",failed:"任务未能完成",cancelled:"任务已停止",local_analysis:"正在扫描全文问题",local_learning:"正在提炼全文写法"};
  const total=Number(task.total_windows||0),done=Number(task.completed_windows||0);
  const reused=Number(task.reused_windows||0),current=Number(task.current_window||0);
  const elapsedEnd=task.finished_at?Date.parse(task.finished_at):Date.now();
  const elapsed=task.started_at?Math.max(0,Math.floor((elapsedEnd-Date.parse(task.started_at))/1000)):0;
  const elapsedText=elapsed>=60?`${Math.floor(elapsed/60)}分${String(elapsed%60).padStart(2,"0")}秒`:`${elapsed}秒`;
  const showIndeterminate=["queued","running"].includes(task.status);
  const progress=total?`<progress max="${total}" value="${done}"></progress><span>${done} / ${total} 个文本窗口</span>`:showIndeterminate?'<progress></progress>':"";
  const resume=reused?`<p class="skill-meta">已复用 ${reused} 个窗口${current?`，正在分析第 ${current} 个窗口`:"，正文窗口已经全部完成"}。</p>`:"";
  const result=task.status==="completed"?`<p>结果：${task.summary||`已完成 ${done||total||1} 个处理步骤`}。你现在可以查看下方结果，再决定是否保留或应用。</p>`:task.status==="failed"?`<p>原因：${escapeHtml(task.error||"未知错误")}。已有本地内容不会丢失，再次运行会复用已经完成的窗口。</p>`:"";
  const stop=task.id&&["queued","running"].includes(task.status)?`<button class="secondary" data-reference-task-cancel="${task.id}">停止分析</button>`:"";
  return `<div><strong>${labels[task.status]||"分析状态"}</strong><p>${phases[task.phase]||"正在处理"} · 已用时 ${elapsedText}</p>${progress}${resume}${result}</div>${stop}`;
}

function renderAttractionMap() {
  const node=state.attractionMap;if(!node?.data)return "";
  const data=node.data,fit={strong:"结构证据完整",partial:"部分结构可以确认",not_applicable:"不适合强套七步"}[data.fit?.level]||"需要复核";
  const goal=data.core_goal||{},opening=data.opening||{},ending=data.ending||{},reversal=data.reversal||null;
  const cycles=Array.isArray(data.cycles)?data.cycles:[],questions=Array.isArray(data.question_chain)?data.question_chain:[],relationships=Array.isArray(data.relationship_arc)?data.relationship_arc:[],uncertainties=Array.isArray(data.uncertainties)?data.uncertainties:[];
  const zh=(value,fallback)=>readableModelText(value,fallback);
  const evidence=value=>{const items=Array.isArray(value)?value:[];return items.length?`<details><summary>查看原文依据（${items.length}处）</summary>${items.slice(0,8).map(item=>`<blockquote>${escapeHtml(item.excerpt||item)}</blockquote>`).join("")}</details>`:""};
  const projectOptions=state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("");
  const actions=node.status==="confirmed"?`<div class="attraction-actions"><label>应用到作品<select data-attraction-project><option value="">选择作品</option>${projectOptions}</select></label><button class="primary" data-attraction-adopt>采纳抽象写法</button></div>`:node.status==="rejected"?'<p class="skill-meta">这份分析已拒绝，不会进入任何作品。</p>':`<div class="attraction-actions"><button class="primary" data-attraction-confirm>确认分析</button><button class="secondary" data-attraction-reject>拒绝分析</button></div>`;
  const cycleRows=cycles.map((item,index)=>item.summary?`<article><b>${index+1}</b><div><strong>${escapeHtml(zh(item.summary,"推进内容待确认"))}</strong>${evidence(item.evidence)}</div></article>`:`<article><b>${index+1}</b><div><strong>遇到：${escapeHtml(zh(item.obstacle,"未确认"))}</strong><p>采取：${escapeHtml(zh(item.effort,"未确认"))}</p><p>得到：${escapeHtml(zh(item.result,"未确认"))}</p><p>真正变化：${escapeHtml(zh(item.state_change,"未确认"))}</p><p>留下的新问题：${escapeHtml(zh(item.next_question,"未确认"))}</p>${evidence(item.evidence)}</div></article>`).join("");
  const accidentRows=(data.accidents||[]).map((item,index)=>`<p><strong>意外 ${index+1}：</strong>${escapeHtml(zh(item.summary||item.content,"内容待确认"))}</p>`).join("");
  const goalSummary=goal.summary?`<p>${escapeHtml(zh(goal.summary,"尚不明确"))}</p>`:`<p>外部：${escapeHtml(zh(goal.surface,"尚不明确"))}</p><p>内心：${escapeHtml(zh(goal.emotional,"尚不明确"))}</p>`;
  const endingSummary=ending.summary?`<p>${escapeHtml(zh(ending.summary,"尚不明确"))}</p>`:`<p>事情结果：${escapeHtml(zh(ending.surface_payoff||ending.surface_goal,"尚不明确"))}</p><p>情感结果：${escapeHtml(zh(ending.emotional_payoff||ending.inner_goal,"尚不明确"))}</p><p>付出代价：${escapeHtml(zh(ending.cost,"尚不明确"))}</p>`;
  return `<section class="attraction-map"><header><div><p class="eyebrow">模型全文分析 · 剧情吸引力</p><h3>${fit}</h3><p>${escapeHtml(zh(data.fit?.explanation,"系统按全文证据整理了可能推动读者继续阅读的结构。"))}</p></div><span>${node.status==="confirmed"?"已确认":node.status==="rejected"?"已拒绝":"等待你确认"}</span></header><div class="attraction-grid"><article><span>开头为什么让人继续看</span><strong>${escapeHtml(zh(opening.transfer_guidance||opening.summary,"目前没有足够证据判断"))}</strong>${evidence(opening.evidence)}</article><article><span>人物一直想完成什么</span>${goalSummary}${evidence(goal.evidence)}</article></div><section class="attraction-cycles"><h4>剧情怎样一轮轮向前走</h4>${cycles.length?cycleRows:'<p class="skill-meta">目前没有足够证据整理出完整推进轮次。</p>'}${accidentRows?`<details><summary>查看改变后续走向的意外（${data.accidents.length}个）</summary>${accidentRows}</details>`:""}</section><div class="attraction-grid"><article><span>问题与答案是否接得上</span><strong>${questions.length?`${questions.length}条问题链`:"目前没有完整问题链"}</strong>${questions.slice(0,4).map(item=>`<p>${escapeHtml(zh(item.question,"问题未命名"))} → ${escapeHtml(zh(item.answer||item.next_question,"尚未回答"))}</p>`).join("")}</article><article><span>人物关系怎样变化</span><strong>${relationships.length?`${relationships.length}次有原因的变化`:"目前没有明确关系变化"}</strong>${relationships.slice(0,4).map(item=>`<p>${escapeHtml(zh(item.before,"之前"))} → ${escapeHtml(zh(item.after,"之后"))}，因为${escapeHtml(zh(item.cause,"原因未确认"))}</p>`).join("")}</article><article><span>反转是否有前文依据</span><strong>${escapeHtml(zh(reversal?.content,"没有确认到有效反转"))}</strong>${reversal?evidence(reversal.prior_evidence):""}</article><article><span>结尾最终兑现什么</span>${endingSummary}${evidence(ending.evidence)}</article></div>${uncertainties.length?`<details class="attraction-uncertainty"><summary>目前只能确定到这里（${uncertainties.length}项）</summary><ul>${uncertainties.map(item=>`<li>${escapeHtml(zh(item,"这项内容还没有足够证据"))}</li>`).join("")}</ul></details>`:""}${actions}</section>`;
}

function renderLocalAttractionCandidates(candidates){
  if(!candidates)return "";
  const opening=candidates.opening||{};
  const signalCount=["pressure","anomaly","question","future_promise"].filter(key=>(opening[key]||[]).length).length;
  return `<details class="local-attraction-candidates"><summary><span><strong>本地吸引力候选</strong><small>全文覆盖 ${Number(candidates.coverage_percent||0)}% · 开头 ${signalCount}/4 类信号</small></span><span>展开</span></summary><div><p>问题候选：${(candidates.questions||[]).length}处 · 行动选择：${(candidates.decisions||[]).length}处 · 后果变化：${(candidates.consequences||[]).length}处 · 转折信号：${(candidates.turns||[]).length}处 · 关系变化：${(candidates.relationship_changes||[]).length}处</p><p>${escapeHtml(candidates.boundary||"这些位置需要结合上下文确认。")}</p></div></details>`;
}

function renderReferenceTaskStatus(){
  const shell=$("[data-reference-task-status]");if(!shell)return;
  const task=state.referenceTask;
  shell.className=`reference-task-status ${task?.status||"idle"}`;
  shell.innerHTML=referenceTaskMarkup();
  shell.querySelector("[data-reference-task-cancel]")?.addEventListener("click",cancelReferenceAnalysisTask);
}

function renderReferenceDetail() {
  const source = state.activeReference;
  if (!source) return;
  const typeLabels={reference_work:"参考作品",platform_rule:"平台规则",popular_sample:"爆款样本",writing_tutorial:"写作教程",competitor_work:"竞品作品"};
  const sourceTypeLabels={paste:"粘贴文本",txt:"文本文件",docx:"文字文档",pdf:"电子文档",url:"网页资料"};
  const report = state.referenceAnalysis?.result;
  const metrics = report?.metrics;
  const findings = report?.findings || [];
  const learning=state.learningReport?.source_id===source.id?state.learningReport:null;
  const learningSummary=learning?`<section class="reference-learning-summary"><div><strong>${learning.analyzed_windows} / ${learning.window_count}</strong><span>窗口已扫描</span></div><div><strong>${learning.coverage_percent}%</strong><span>全文覆盖率</span></div><div><strong>${learning.mechanisms.length}</strong><span>合并后候选机制</span></div><p>本地规则已覆盖全文；候选机制的多处证据已合并，可在下方项目学习区查看。</p></section>`:"";
  const diagnosticsHtml=metrics?`<section class="reference-metrics"><div><strong>${metrics.sentence_count}</strong><span>句子</span></div><div><strong>${metrics.paragraph_count}</strong><span>段落</span></div><div><strong>${metrics.average_sentence_length}</strong><span>平均句长</span></div><div><strong>${findings.length}</strong><span>需要你复核</span></div></section><section class="reference-findings"><h3>本地诊断</h3><p class="section-intro">这些是本地规则找到的疑似位置，不代表文章一定有错。请结合原文决定是否修改。</p>${findings.length?findings.map(renderDiagnosticFinding).join(""):'<p class="skill-meta">当前没有发现需要你复核的问题。</p>'}</section>`:'<section><p class="skill-meta">尚未运行本地诊断。点击后会扫描全文，并说明每个疑似问题为什么值得检查。</p></section>';
  $("#reference-detail").innerHTML = `<header><div><p class="eyebrow">${escapeHtml(sourceTypeLabels[source.source_type]||"参考资料")}</p><h2>${escapeHtml(source.title)}</h2><p class="skill-meta">${Number(source.latest_version?.character_count || 0).toLocaleString()} 字符 · 版本 ${source.latest_version?.version || 1}</p></div><div class="reference-actions"><button class="primary" data-reference-create>从此资料创建作品</button><button class="secondary" data-reference-analyze>本地诊断</button><button class="secondary" data-reference-learn>本地提炼</button><button class="secondary" data-reference-model-learn>模型全文分析</button><button class="secondary danger-text" data-reference-delete>删除</button></div></header><section class="reference-task-status" data-reference-task-status></section>${learningSummary}${renderLocalAttractionCandidates(learning?.attraction_candidates)}${renderAttractionMap()}${diagnosticsHtml}<details class="reference-source"><summary>查看原文</summary><pre>${escapeHtml(state.referenceContent)}</pre></details>`;
  renderReferenceTaskStatus();
  $("#reference-detail [data-reference-analyze]").addEventListener("click", analyzeReference);
  $("#reference-detail [data-reference-learn]").addEventListener("click", learnReference);
  $("#reference-detail [data-reference-model-learn]").addEventListener("click", modelLearnReference);
  $("#reference-detail [data-reference-create]").addEventListener("click", startWizardFromReference);
  $("#reference-detail [data-reference-delete]").addEventListener("click", deleteReference);
  $("#reference-detail [data-attraction-confirm]")?.addEventListener("click",()=>reviseAttractionMap("confirm"));
  $("#reference-detail [data-attraction-reject]")?.addEventListener("click",()=>reviseAttractionMap("reject"));
  $("#reference-detail [data-attraction-adopt]")?.addEventListener("click",adoptAttractionMap);
  const header=$("#reference-detail header");
  const metadata=document.createElement("section");
  metadata.className="reference-metadata";
  metadata.innerHTML=`<label>平台<input data-reference-platform maxlength="80" value="${escapeHtml(source.platform||"")}"></label><label>内容类型<select data-reference-type>${Object.entries(typeLabels).map(([value,label])=>`<option value="${value}" ${value===source.content_type?"selected":""}>${label}</option>`).join("")}</select></label><label>关联写作项目<select data-reference-project><option value="">不关联写作项目</option>${state.projects.map(item=>`<option value="${item.id}" ${item.id===source.project_id?"selected":""}>${escapeHtml(item.title)}</option>`).join("")}</select></label><div class="reference-metadata-action"><span class="reference-save-state" data-reference-metadata-status>✓ 已保存</span><button class="primary" data-reference-metadata-save hidden>保存修改</button></div>${source.content_type==="popular_sample"?'<button class="secondary" data-reference-popular>爆款分析</button>':""}`;
  header.insertAdjacentElement("afterend",metadata);
  metadata.querySelector("[data-reference-metadata-save]").addEventListener("click",saveReferenceMetadata);
  metadata.querySelector("[data-reference-platform]").addEventListener("input",markReferenceMetadataDirty);
  metadata.querySelector("[data-reference-type]").addEventListener("change",markReferenceMetadataDirty);
  metadata.querySelector("[data-reference-project]").addEventListener("change",markReferenceMetadataDirty);
  metadata.querySelector("[data-reference-popular]")?.addEventListener("click",analyzePopularReference);
  const marketPanel=document.createElement("section");
  marketPanel.className="reference-market-panel";
  const context=source.market_context;
  marketPanel.innerHTML=context
    ? `<div><p class="eyebrow">榜单关联</p><h3>已关联《${escapeHtml(context.title)}》</h3><p class="skill-meta">${escapeHtml(platformLabel(context.platform))} · ${escapeHtml(context.current?.ranking_name||"暂无当前榜单")} ${context.current?.rank?`第 ${context.current.rank} 名`:""} · 市场数据 ${escapeHtml(formatLocalTimestamp(context.current?.captured_at)||"尚未更新")}</p></div><button class="secondary danger-text" data-market-unlink>解除榜单关联</button>`
    : `<div><p class="eyebrow">榜单匹配</p><h3>榜单作品匹配</h3><p class="skill-meta">根据文件名、作品名和正文开头在本地查找候选，不会自动关联。</p></div><button class="secondary" data-market-match>查找榜单匹配</button><div class="market-match-results" data-market-match-results></div>`;
  metadata.insertAdjacentElement("afterend",marketPanel);
  marketPanel.querySelector("[data-market-match]")?.addEventListener("click",()=>matchReferenceMarket(source.id));
  marketPanel.querySelector("[data-market-unlink]")?.addEventListener("click",()=>unlinkReferenceMarket(source.id));
  if(!context&&state.marketMatch?.reference_id===source.id) renderReferenceMarketCandidates(marketPanel,state.marketMatch);
}

async function matchReferenceMarket(referenceId){
  try{
    state.marketMatch=await api(`/api/market/references/${referenceId}/match`);
    const panel=$("#reference-detail .reference-market-panel");
    if(panel)renderReferenceMarketCandidates(panel,state.marketMatch);
  }catch(error){toast(error.message);}
}

function renderReferenceMarketCandidates(panel,result){
  const shell=panel.querySelector("[data-market-match-results]");
  if(!shell)return;
  if(!result.candidates.length){
    shell.innerHTML='<p class="skill-meta">当前榜单索引没有找到候选，可继续作为普通文本资料使用。</p>';
    return;
  }
  const label=result.status==="high"?"高度可信":"需要确认";
  shell.innerHTML=`<p class="market-match-label">${label}</p>${result.candidates.map(item=>`<article><div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(platformLabel(item.platform))} · ${escapeHtml(item.ranking_name||"榜单")} · ${escapeHtml(item.category||"未分类")}</span><small>${item.reasons.map(escapeHtml).join(" · ")}</small></div><button class="primary" data-market-link="${escapeHtml(item.work_id)}">确认关联</button></article>`).join("")}`;
  shell.querySelectorAll("[data-market-link]").forEach(button=>button.addEventListener("click",()=>linkReferenceMarket(result.reference_id,button.dataset.marketLink)));
}

async function linkReferenceMarket(referenceId,workId){
  try{
    await api(`/api/market/references/${referenceId}/link`,{method:"PUT",body:JSON.stringify({work_id:workId})});
    state.activeReference=await api(`/api/references/${referenceId}`);
    state.references=await api("/api/references");
    state.marketMatch=null; renderReferences(); toast("榜单作品关联已确认");
  }catch(error){toast(error.message);}
}

async function unlinkReferenceMarket(referenceId){
  if(!confirm("解除榜单关联？文本正文和资料分类会继续保留。"))return;
  try{
    await api(`/api/market/references/${referenceId}/link`,{method:"DELETE"});
    state.activeReference=await api(`/api/references/${referenceId}`);
    state.references=await api("/api/references");
    state.marketMatch=null; renderReferences(); toast("已解除榜单关联");
  }catch(error){toast(error.message);}
}

function markReferenceMetadataDirty(){
  const shell=$("#reference-detail .reference-metadata"); if(!shell||!state.activeReference)return;
  const dirty=(shell.querySelector("[data-reference-platform]").value.trim()||null)!==(state.activeReference.platform||null)
    ||shell.querySelector("[data-reference-type]").value!==state.activeReference.content_type
    ||(shell.querySelector("[data-reference-project]").value||null)!==(state.activeReference.project_id||null);
  const button=shell.querySelector("[data-reference-metadata-save]");
  button.hidden=!dirty; button.disabled=false; button.textContent="保存修改";
  const status=shell.querySelector("[data-reference-metadata-status]");
  status.hidden=dirty; status.textContent="✓ 已保存";
}

async function saveReferenceMetadata(){
  const shell=$("#reference-detail .reference-metadata");
  const button=shell.querySelector("[data-reference-metadata-save]");
  try{
    button.hidden=false; button.disabled=true; button.textContent="保存中…";
    shell.querySelector("[data-reference-metadata-status]").hidden=true;
    const source=await api(`/api/references/${state.activeReference.id}/metadata`,{method:"PATCH",body:JSON.stringify({platform:shell.querySelector("[data-reference-platform]").value.trim()||null,content_type:shell.querySelector("[data-reference-type]").value,project_id:shell.querySelector("[data-reference-project]").value||null})});
    state.activeReference=source; await loadAll(); toast("资料分类已保存；相关已采纳机制已标记为待复核（如有）");
  }catch(error){
    button.hidden=false; button.disabled=false; button.textContent="重试保存";
    const status=shell.querySelector("[data-reference-metadata-status]");status.hidden=false;status.textContent="保存失败，请重试";status.classList.add("failed");
    toast(error.message);
  }
}

async function analyzePopularReference(){
  try{
    const report=await api(`/api/references/${state.activeReference.id}/popular-analysis`,{method:"POST"});
    const labels={title:"标题",first_three_lines:"前三行",opening_500:"前500字",middle:"中段",turning_points:"转折",ending:"结尾"};
    const section=document.createElement("section"); section.className="reference-findings popular-report";
    section.innerHTML=`<h3>爆款样本本地分析</h3>${Object.entries(report.sections).map(([key,value])=>`<article><strong>${labels[key]}</strong><p>${value.findings.length?value.findings.map(escapeHtml).join("；"):"当前本地指标未发现明显缺口"}</p>${value.evidence.slice(0,3).map(item=>`<blockquote>${escapeHtml(item.excerpt)}</blockquote>`).join("")}</article>`).join("")}`;
    $("#reference-detail .reference-source").insertAdjacentElement("beforebegin",section);
    toast("爆款样本分析完成（未调用模型）");
  }catch(error){toast(error.message);}
}

async function analyzeReference() {
  if (!state.activeReference) return;
  state.referenceTask={status:"running",phase:"local_analysis",started_at:new Date().toISOString(),completed_windows:0,total_windows:0};renderReferenceTaskStatus();
  try {
    state.referenceAnalysis = await api(`/api/references/${state.activeReference.id}/analyze`, {method:"POST"});
    if (state.localNlp?.enabled) await api(`/api/references/${state.activeReference.id}/nlp`, {method:"POST"});
    state.referenceTask={...state.referenceTask,status:"completed",phase:"completed",finished_at:new Date().toISOString(),summary:`全文扫描完成，发现 ${state.referenceAnalysis.result?.findings?.length||0} 处需要你复核`};
    renderReferenceDetail();
    toast(state.referenceAnalysis.cached ? "已加载本地分析缓存" : "本地分析完成");
  } catch(error) { state.referenceTask={...state.referenceTask,status:"failed",phase:"failed",finished_at:new Date().toISOString(),error:error.message};renderReferenceTaskStatus();toast(error.message); }
}

async function loadReferenceAnalysisTask(sourceId){
  try{
    const task=await api(`/api/references/${sourceId}/model-learn/status`);
    if(state.activeReference?.id!==sourceId)return;
    state.referenceTask=task;renderReferenceTaskStatus();
    if(["queued","running"].includes(task.status))pollReferenceAnalysisTask(sourceId);
  }catch(error){console.warn("Unable to restore reference analysis status",error);}
}

async function pollReferenceAnalysisTask(sourceId){
  clearTimeout(state.referenceTaskTimer);
  if(state.activeReference?.id!==sourceId)return;
  try{
    const previous=state.referenceTask?.status;
    const task=await api(`/api/references/${sourceId}/model-learn/status`);
    if(state.activeReference?.id!==sourceId)return;
    state.referenceTask=task;
    if(task.status==="completed"&&previous!=="completed"){
      state.mechanisms=await api("/api/learning/mechanisms");
      state.attractionMap=task.result?.attraction_map||await api(`/api/references/${sourceId}/attraction-map`);
      const count=task.result?.mechanisms?.length||0;
      task.summary=count?`全文模型分析完成，得到 ${count} 个候选写法`:"全文模型分析完成；模型未形成可逐条采纳的候选写法，剧情吸引力报告仍可查看";
      renderLearning();renderReferenceDetail();
    }
    renderReferenceTaskStatus();
    if(["queued","running"].includes(task.status))state.referenceTaskTimer=setTimeout(()=>pollReferenceAnalysisTask(sourceId),1200);
  }catch(error){
    state.referenceTask={...state.referenceTask,status:"failed",phase:"failed",error:error.message};renderReferenceTaskStatus();
  }
}

async function cancelReferenceAnalysisTask(event){
  const taskId=event.currentTarget.dataset.referenceTaskCancel,sourceId=state.activeReference?.id;if(!taskId||!sourceId)return;
  try{state.referenceTask=await api(`/api/references/${sourceId}/model-learn/${taskId}`,{method:"DELETE"});renderReferenceTaskStatus();}
  catch(error){toast(error.message);}
}

async function reviseAttractionMap(action){
  if(!state.attractionMap)return;
  try{
    state.attractionMap=await api(`/api/learning/nodes/${state.attractionMap.id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})});
    renderReferenceDetail();toast(action==="confirm"?"剧情吸引力分析已确认，可选择作品采纳":"分析已拒绝，不会进入作品");
  }catch(error){toast(error.message);}
}

async function adoptAttractionMap(){
  const projectId=$("[data-attraction-project]")?.value;if(!projectId)return toast("请先选择要应用的作品");
  try{
    await api(`/api/projects/${projectId}/learning/adoptions/${state.attractionMap.id}`,{method:"POST",body:JSON.stringify({edits:{}})});
    toast("已只采纳抽象写法，原文人物、设定和表达不会进入作品");
  }catch(error){toast(error.message);}
}

async function deleteReference() {
  if (!state.activeReference || !confirm(`删除“${state.activeReference.title}”及其本地原文？`)) return;
  try {
    await api(`/api/references/${state.activeReference.id}`, {method:"DELETE"});
    state.activeReference = null; state.referenceContent = ""; state.referenceAnalysis = null;
    await loadAll(); toast("参考资料已删除");
  } catch(error) { toast(error.message); }
}

$("#reference-form").addEventListener("submit", async event => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector('button[type="submit"]');
  const status = $("#reference-import-status");
  const file = $("#reference-file").files[0];
  const url = $("#reference-url").value.trim();
  const extension = file?.name.split(".").pop().toLowerCase();
  const text = file && extension === "txt" ? await file.text() : $("#reference-text").value;
  const title = $("#reference-title").value.trim() || file?.name.replace(/\.(txt|docx|pdf)$/i, "") || url;
  const metadata={platform:$("#reference-platform").value||null,content_type:$("#reference-content-type").value||null,project_id:$("#reference-project").value||null};
  if (!file && !url && !text.trim()) return toast("请选择文档、输入网址或粘贴正文");
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "正在保存…";
  status.className="operation-status busy";
  status.textContent = url ? "正在读取网页内容并保存资料，公开网页最多等待约 20 秒。" : "正在保存资料，不会调用模型。";
  try {
    let source;
    if (url) source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:"url",source_uri:url,...metadata})});
    else if (file && extension !== "txt") source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:extension,source_uri:file.name,data_base64:await fileBase64(file),...metadata})});
    else source = await api("/api/references", {method:"POST", body:JSON.stringify({title, text, source_type:file ? "txt" : "paste",...metadata})});
    event.target.reset(); state.activeReference = source; state.referenceContent = ""; state.referenceAnalysis = null; state.importReceipt=source.import_receipt;
    state.marketMatch=await api(`/api/market/references/${source.id}/match`).catch(()=>null);
    status.className="operation-status success";status.textContent = "资料已保存。下方结果单说明系统会怎样使用它。";
    await loadAll(); renderImportReceipt(); toast("资料已保存");
  } catch(error) {
    status.className="operation-status error";status.textContent = `保存失败：${error.message}。表单内容仍在，可以修改后重试。`;
    toast(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
});
const fileBase64 = file => new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result).split(",")[1]); reader.onerror=reject; reader.readAsDataURL(file); });
["reference-search","reference-filter-platform","reference-filter-type","reference-filter-project"].forEach(id=>$("#"+id)?.addEventListener(id==="reference-search"?"input":"change",renderReferences));

function marketQuery(){
  const params=new URLSearchParams();
  const platform=$("#market-platform")?.value||"";
  const ranking=$("#market-ranking")?.value||"";
  const category=$("#market-category")?.value||"";
  const lengthType=$("#market-length-type")?.value||"";
  if(platform)params.set("platform",platform);
  if(ranking)params.set("ranking",ranking);
  if(category)params.set("category",category);
  if(lengthType)params.set("length_type",lengthType);
  params.set("days",$("#market-period")?.value||"30");
  return params.toString();
}

async function loadMarketDashboard(){
  const shell=$("#market-refresh-state");
  if(shell)shell.textContent="正在读取本地市场快照…";
  try{
    [state.market,state.marketBaselines]=await Promise.all([api(`/api/market/dashboard?${marketQuery()}`),api("/api/market/baselines")]);
    renderMarketDashboard();
    renderMarketBaselineSelector();
  }catch(error){
    if(shell){shell.className="market-refresh-state error";shell.textContent=`读取失败：${error.message}`;}
  }
}

function renderMarketBaselineSelector(){
  const select=$("#market-baseline-cohort");if(!select)return;
  const selected=select.value;
  const labels={insufficient:"样本不足",preliminary:"初步",advisory:"可用于建议"};
  select.innerHTML=state.marketBaselines.length?state.marketBaselines.map((item,index)=>{const key=item.key;return `<option value="${index}">${escapeHtml(platformLabel(key.platform))} · ${escapeHtml(key.ranking_name)} · ${escapeHtml(key.category)} · ${escapeHtml(lengthTypeLabel(key.length_type))}（${item.sample_count}篇，${labels[item.confidence_level]}）</option>`;}).join(""):'<option value="">暂无可用样本组</option>';
  if(selected!==""&&state.marketBaselines[Number(selected)])select.value=selected;
  if(state.marketBaselines.length)loadMarketBaseline(Number(select.value||0));
  else $("#market-baseline-detail").innerHTML='<p class="market-empty">关联榜单作品并运行本地提炼后生成同类样本观察。</p>';
}

async function loadMarketBaseline(index){
  const cohort=state.marketBaselines[index];if(!cohort)return;
  try{state.marketBaseline=await api(`/api/market/baseline?${new URLSearchParams(cohort.key)}`);renderMarketBaseline();}
  catch(error){$("#market-baseline-detail").innerHTML=`<p class="market-empty">${escapeHtml(error.message)}</p>`;}
}

function renderMarketBaseline(){
  const data=state.marketBaseline;if(!data)return;
  const labels={insufficient:"样本不足，仅展示观察",preliminary:"初步基线",advisory:"可用于项目建议"};
  const mechanisms=data.mechanisms.slice(0,8);
  const samples=data.samples||[];
  $("#market-baseline-detail").innerHTML=`<div class="market-baseline-summary"><div><strong>${data.sample_count}</strong><span>原始有效作品数</span></div><div><strong>${labels[data.confidence_level]}</strong><span>可信状态</span></div><div><strong>${escapeHtml(data.date_range?`${data.date_range.start} 至 ${data.date_range.end}`:"暂无")}</strong><span>样本日期</span></div></div><div class="market-baseline-opening"><span>前500字明确问题 <strong>${data.opening.question_percent}%</strong></span><span>前500字异常信号 <strong>${data.opening.anomaly_percent}%</strong></span></div>${mechanisms.length?`<div class="market-baseline-mechanisms">${mechanisms.map(item=>`<article><div><strong>${escapeHtml(item.name)}</strong><span>${item.work_count}/${data.sample_count}篇 · 原始占比 ${item.prevalence_percent}% · 综合参考 ${item.weighted_prevalence_percent??item.prevalence_percent}%</span></div><small>${item.position_median===null?"暂无稳定位置":`全文中位位置 ${item.position_median}%`}</small></article>`).join("")}</div>`:'<p class="market-empty">当前样本尚未完成本地提炼，暂无可汇总机制。</p>'}${samples.length?`<details class="market-sample-weights"><summary>查看每份样本为什么有参考价值</summary>${samples.map(item=>`<p><strong>${escapeHtml(item.title)}</strong><span>参考强度 ${Math.round(item.weight*100)}% · ${item.weight_reasons.map(escapeHtml).join(" · ")}</span></p>`).join("")}</details>`:""}<p class="market-baseline-boundary">${escapeHtml(data.boundary)}</p>`;
}

function marketMetricText(metrics){
  const entries=Object.entries(metrics||{});
  if(!entries.length)return "暂无指标";
  const labels={likes:"赞",black_horse_index:"黑马指数"};
  return entries.map(([key,value])=>`${Number(value).toLocaleString()} ${labels[key]||key}`).join(" · ");
}

function renderMarketDashboard(){
  const data=state.market;if(!data)return;
  const summary=data.summary;
  $("#market-summary").innerHTML=[
    ["收录作品",summary.work_count+" 部"],["热门分类",summary.hot_category||"暂无"],
    ["上升分类",summary.rising_category||(data.trend_ready?"暂无":"待积累")],
    ["有效快照",summary.snapshot_count+" 次"],["已关联文本",summary.linked_count+" 份"],
  ].map(([label,value])=>`<article><span>${label}</span><strong>${escapeHtml(value)}</strong></article>`).join("");
  const refresh=data.refresh||{};
  const stateLabel=refresh.status==="success"?"最近更新成功":refresh.status==="failed"?"最近更新失败":"尚未更新榜单";
  $("#market-refresh-state").className=`market-refresh-state ${refresh.status||""}`;
  $("#market-refresh-state").textContent=`${stateLabel}${refresh.last_success_at?` · ${formatLocalTimestamp(refresh.last_success_at)}`:""}${refresh.error?` · ${refresh.error}`:""}`;
  $("#market-boundary").textContent=`数据边界：${data.boundary} 页面推荐也可能受到平台运营和账号展示差异影响。`;
  updateMarketFilters(data);
  renderMarketShare(data.categories);
  renderMarketTrend(data);
  renderMarketHeat(data.categories);
  renderMarketRankings(data.rankings);
  renderMarketKeywords(data.keywords||{});
  $("#market-work-count").textContent=`${data.rankings.length} 个榜单 · ${data.works.length} 条记录${refresh.last_success_at?` · ${formatLocalTimestamp(refresh.last_success_at)}`:""}`;
  renderMarketWorks(data.works);
}

function renderMarketKeywords(groups){
  const source=$("#market-keyword-source")?.value||"combined";
  const selectedCategory=$("#market-keyword-category")?.value||"";
  const all=groups[source]||[];
  const categories=[...new Set(all.map(item=>item.category))];
  const categorySelect=$("#market-keyword-category");
  if(categorySelect){
    categorySelect.innerHTML='<option value="">全部分类</option>'+categories.map(item=>`<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
    if(categories.includes(selectedCategory))categorySelect.value=selectedCategory;
  }
  const items=all.filter(item=>!selectedCategory||item.category===selectedCategory);
  $("#market-keywords").innerHTML=items.length?items.map((item,index)=>`<button type="button" data-market-keyword="${escapeHtml(item.word)}" style="--rank:${index}" title="覆盖 ${item.share}%，综合分 ${item.score}" aria-pressed="false"><span class="market-keyword-kind">${escapeHtml(item.category)}</span><strong>${escapeHtml(item.word)}</strong><span>${item.work_count} 部 · ${item.score}分</span></button>`).join(""):'<p class="market-empty">当前范围没有跨作品重复词（至少需出现在 2 部作品中）</p>';
  $("#market-keywords").querySelectorAll("[data-market-keyword]").forEach(button=>button.addEventListener("click",()=>{
    const item=items.find(entry=>entry.word===button.dataset.marketKeyword);
    if(state.activeMarketKeyword===item.word){closeMarketKeywordEvidence();return;}
    state.activeMarketKeyword=item.word;
    $("#market-keywords").querySelectorAll("[data-market-keyword]").forEach(candidate=>{const active=candidate===button;candidate.classList.toggle("active",active);candidate.setAttribute("aria-pressed",String(active));});
    const evidence=$("#market-keyword-evidence");
    evidence.hidden=false;
    evidence.innerHTML=`<div><strong>${escapeHtml(item.word)}</strong><span>覆盖 ${item.work_count} 部（${item.share}%） · 前五 ${item.top_five_count} 部 · 跨 ${item.ranking_count} 个榜单</span><button type="button" class="icon-button" data-market-keyword-close aria-label="收起热门词详情" title="收起">×</button></div>${item.works.map(work=>{const daily=work.daily_best;const period=work.period_best;const dailyText=daily?`${daily.date} 当日最高第 ${daily.rank??"—"} 名 · ${daily.ranking_name}`:`当前最高第 ${work.rank??"—"} 名`;const periodText=period?`周期最高第 ${period.rank??"—"} 名 · ${period.date} · ${period.ranking_name}`:"";return `<article><strong>${escapeHtml(work.title)}</strong><small>${escapeHtml(dailyText)}${periodText?` · ${escapeHtml(periodText)}`:""}</small><p>${escapeHtml(work.excerpt||"")}</p></article>`;}).join("")}`;
    evidence.querySelector("[data-market-keyword-close]").addEventListener("click",closeMarketKeywordEvidence);
  }));
}

function closeMarketKeywordEvidence(){
  state.activeMarketKeyword=null;
  const evidence=$("#market-keyword-evidence");
  evidence.hidden=true;evidence.innerHTML="";
  $("#market-keywords")?.querySelectorAll("[data-market-keyword]").forEach(button=>{button.classList.remove("active");button.setAttribute("aria-pressed","false");});
}
document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!$("#market-keyword-evidence")?.hidden)closeMarketKeywordEvidence();});

function updateMarketFilters(data){
  const ranking=$("#market-ranking"),category=$("#market-category");
  const rankingValue=ranking.value,categoryValue=category.value;
  const rankings=[...new Set(data.works.map(item=>item.ranking_name).filter(Boolean))];
  const categories=[...new Set(data.works.map(item=>item.category||item.original_category).filter(Boolean))];
  ranking.innerHTML='<option value="">全部榜单</option>'+rankings.map(item=>`<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
  category.innerHTML='<option value="">全部分类</option>'+categories.map(item=>`<option value="${escapeHtml(item)}">${escapeHtml(item)}</option>`).join("");
  if(rankings.includes(rankingValue))ranking.value=rankingValue;
  if(categories.includes(categoryValue))category.value=categoryValue;
}

function renderMarketShare(categories){
  const shell=$("#market-share-chart");
  if(!categories.length){shell.innerHTML='<p class="market-empty">暂无分类样本</p>';return;}
  const colors=["#6d5dfc","#25a477","#e4a83a","#4d78c9","#d56b66","#8e67ae"];
  let cursor=0;
  const stops=categories.map((item,index)=>{const start=cursor;cursor+=item.share;return `${colors[index%colors.length]} ${start}% ${cursor}%`;});
  shell.innerHTML=`<div class="market-donut" style="background:conic-gradient(${stops.join(",")})"><span>${categories.reduce((sum,item)=>sum+item.count,0)}<small>条记录</small></span></div><div class="market-legend">${categories.map((item,index)=>`<button type="button" data-market-category-filter="${escapeHtml(item.name)}"><i style="background:${colors[index%colors.length]}"></i><span>${escapeHtml(item.name)}</span><strong>${item.share}%</strong></button>`).join("")}</div>`;
  shell.querySelectorAll("[data-market-category-filter]").forEach(button=>button.addEventListener("click",()=>{$("#market-category").value=button.dataset.marketCategoryFilter;loadMarketDashboard();}));
}

function renderMarketTrend(data){
  const shell=$("#market-trend-chart");
  if(!data.trend_ready){shell.innerHTML=`<div class="market-empty"><strong>继续积累快照</strong><span>当前 ${data.summary.snapshot_count} 次，至少更新2次后生成真实趋势。</span></div>`;return;}
  const names=data.categories.slice(0,4).map(item=>item.name),points=data.trend_series;
  const max=Math.max(1,...points.flatMap(point=>names.map(name=>point.categories[name]||0)));
  const width=420,height=180,pad=24;
  const colors=["#6d5dfc","#25a477","#e4a83a","#4d78c9"];
  const lines=names.map((name,index)=>{
    const coords=points.map((point,i)=>`${pad+i*(width-pad*2)/Math.max(1,points.length-1)},${height-pad-(point.categories[name]||0)*(height-pad*2)/max}`).join(" ");
    return `<polyline points="${coords}" fill="none" stroke="${colors[index]}" stroke-width="3"/>`;
  }).join("");
  shell.innerHTML=`<svg class="market-line-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="分类趋势折线图">${lines}</svg><div class="market-inline-legend">${names.map((name,index)=>`<span><i style="background:${colors[index]}"></i>${escapeHtml(name)}</span>`).join("")}</div>`;
}

function renderMarketHeat(categories){
  const shell=$("#market-heat-chart");
  shell.innerHTML=categories.length?categories.map(item=>`<div class="market-bar"><span>${escapeHtml(item.name)}</span><div><i style="width:${item.heat}%"></i></div><strong>${item.heat}</strong><small>竞争${item.competition} · ${item.trend}</small></div>`).join(""):'<p class="market-empty">暂无热度数据</p>';
}

function renderMarketRankings(rankings){
  const shell=$("#market-ranking-chart");
  const names=[...new Set(rankings.flatMap(item=>Object.keys(item.categories)))].sort();
  const colors=["#6757d9","#218a6b","#c48622","#3976b8","#c65d66","#7d5aa6","#287f91","#8a7041"];
  const colorFor=new Map(names.map((name,index)=>[name,colors[index%colors.length]]));
  shell.innerHTML=rankings.length?rankings.map(item=>{
    const total=Object.values(item.categories).reduce((a,b)=>a+b,0);
    const categories=Object.entries(item.categories).sort((a,b)=>b[1]-a[1]||a[0].localeCompare(b[0],"zh-CN"));
    return `<article class="market-ranking-row"><header><strong>${escapeHtml(item.name)}</strong><span>${total} 部作品</span></header><div class="market-ranking-track">${categories.map(([name,count])=>{const share=Math.round(count*1000/total)/10;return `<button type="button" class="market-ranking-segment" data-market-category-filter="${escapeHtml(name)}" style="--ranking-color:${colorFor.get(name)};flex:${count}" title="${escapeHtml(name)} · ${count} 部 · ${share}%" aria-label="筛选${escapeHtml(name)}，${count}部，占${share}%">${share>=12?`<span>${share}%</span>`:""}</button>`;}).join("")}</div><div class="market-ranking-legend">${categories.map(([name,count])=>{const share=Math.round(count*1000/total)/10;return `<button type="button" class="market-ranking-legend-item" data-market-category-filter="${escapeHtml(name)}" style="--ranking-color:${colorFor.get(name)}"><i></i><span>${escapeHtml(name)}</span><strong>${count} 部 · ${share}%</strong></button>`;}).join("")}</div></article>`;
  }).join(""):'<p class="market-empty">暂无榜单分布</p>';
  shell.querySelectorAll("[data-market-category-filter]").forEach(button=>button.addEventListener("click",()=>{$("#market-category").value=button.dataset.marketCategoryFilter;loadMarketDashboard();}));
}

const marketWorkSortValue=item=>Math.max(...Object.values(item.metrics||{}).filter(value=>typeof value==="number"),-1);
const MARKET_WORK_PAGE_SIZE=10;
let marketWorkPage=1;
let expandedMarketRanking;
function marketWorkRow(item,position,combined=false){
  const lengthLabels={long:"长篇",short:"短篇",anthology:"作品集",unknown:"待确认"};
  const originalRank=combined?`<small>${escapeHtml(item.ranking_name)} · 原榜第 ${item.rank??"—"} 名</small>`:`<small>${escapeHtml((item.tags||[]).join(" · "))}</small>`;
  return `<tr><td><strong>${position}</strong></td><td><strong>${escapeHtml(item.title)}</strong>${originalRank}</td><td>${escapeHtml(item.ranking_name)}</td><td>${escapeHtml(item.category||item.original_category||"未分类")}</td><td><select class="market-length-editor" data-market-work-id="${escapeHtml(item.id)}" title="${escapeHtml(item.length_evidence||"暂无判定依据")}"><option value="" ${item.length_override==null?"selected":""}>${escapeHtml(lengthLabels[item.length_type]||"待确认")}（自动）</option><option value="long" ${item.length_override==="long"?"selected":""}>长篇</option><option value="short" ${item.length_override==="short"?"selected":""}>短篇</option><option value="anthology" ${item.length_override==="anthology"?"selected":""}>作品集</option></select><small>${escapeHtml(item.length_source==="user"?"手动确认":item.length_source==="platform"?"平台标记":item.length_source==="ranking"?"榜单推断":"暂无依据")}</small></td><td>${escapeHtml(marketMetricText(item.metrics))}</td><td><span class="badge ${item.reference_id?"":"missing"}">${item.reference_id?"已关联":"未导入"}</span></td></tr>`;
}
function renderMarketWorks(works){
  const shell=$("#market-work-list");
  const pagination=$("#market-work-pagination");
  if(!works.length){shell.innerHTML='<tr><td colspan="7" class="market-empty">尚无榜单数据，点击“更新当前平台”开始建立第一份快照。</td></tr>';return;}
  const mode=document.querySelector('input[name="market-work-mode"]:checked')?.value||"grouped";
  $("#market-rank-heading").textContent=mode==="combined"?"综合序号":"榜内排名";
  if(mode==="combined"){
    const sorted=[...works].sort((a,b)=>marketWorkSortValue(b)-marketWorkSortValue(a)||String(a.ranking_name).localeCompare(String(b.ranking_name),"zh-CN")||(a.rank??999)-(b.rank??999)||String(a.title).localeCompare(String(b.title),"zh-CN"));
    const pageCount=Math.ceil(sorted.length/MARKET_WORK_PAGE_SIZE);
    marketWorkPage=Math.max(1,Math.min(marketWorkPage,pageCount));
    const start=(marketWorkPage-1)*MARKET_WORK_PAGE_SIZE;
    shell.innerHTML=sorted.slice(start,start+MARKET_WORK_PAGE_SIZE).map((item,index)=>marketWorkRow(item,start+index+1,true)).join("");
    pagination.hidden=pageCount<=1;
    pagination.innerHTML=pageCount>1?`<button type="button" class="icon-button" data-market-work-page="${marketWorkPage-1}" aria-label="上一页" ${marketWorkPage===1?"disabled":""}>←</button><span>第 ${marketWorkPage} / ${pageCount} 页</span><button type="button" class="icon-button" data-market-work-page="${marketWorkPage+1}" aria-label="下一页" ${marketWorkPage===pageCount?"disabled":""}>→</button>`:"";
    pagination.querySelectorAll("[data-market-work-page]").forEach(button=>button.addEventListener("click",()=>{marketWorkPage=Number(button.dataset.marketWorkPage);renderMarketWorks(works);}));
  }else{
    const groups=[...works].sort((a,b)=>(a.rank??999)-(b.rank??999)||String(a.title).localeCompare(String(b.title),"zh-CN")).reduce((result,item)=>{const name=item.ranking_name||"未命名榜单";if(!result.has(name))result.set(name,[]);result.get(name).push(item);return result;},new Map());
    const entries=[...groups.entries()].sort(([a],[b])=>a.localeCompare(b,"zh-CN"));
    if(expandedMarketRanking===undefined||(expandedMarketRanking!==null&&!entries.some(([name])=>name===expandedMarketRanking)))expandedMarketRanking=entries[0][0];
    shell.innerHTML=entries.map(([name,items])=>{const expanded=name===expandedMarketRanking;return `<tr class="market-ranking-group"><th colspan="7"><button type="button" data-market-ranking-toggle="${escapeHtml(name)}" aria-expanded="${expanded}"><span>${expanded?"▾":"▸"} ${escapeHtml(name)}</span><small>${items.length} 部作品</small></button></th></tr>${expanded?items.map(item=>marketWorkRow(item,item.rank??"—")).join(""):""}`;}).join("");
    shell.querySelectorAll("[data-market-ranking-toggle]").forEach(button=>button.addEventListener("click",()=>{expandedMarketRanking=expandedMarketRanking===button.dataset.marketRankingToggle?null:button.dataset.marketRankingToggle;renderMarketWorks(works);}));
    pagination.hidden=true;pagination.innerHTML="";
  }
}

$("#market-refresh")?.addEventListener("click",async()=>{
  const button=$("#market-refresh");button.disabled=true;button.textContent="更新中…";
  try{await api("/api/market/refresh",{method:"POST",body:JSON.stringify({source_id:"zhihu-salt"})});await loadMarketDashboard();state.references=await api("/api/references");renderReferences();toast("榜单快照已保存，本地市场分析已同步更新");}
  catch(error){await loadMarketDashboard();toast(error.message);}
  finally{button.disabled=false;button.textContent="更新当前平台";}
});

["market-platform","market-period","market-ranking","market-category","market-length-type"].forEach(id=>$("#"+id)?.addEventListener("change",loadMarketDashboard));
$("#market-baseline-cohort")?.addEventListener("change",event=>loadMarketBaseline(Number(event.target.value)));
[...document.querySelectorAll('input[name="market-work-mode"]')].forEach(input=>input.addEventListener("change",()=>{marketWorkPage=1;expandedMarketRanking=undefined;renderMarketWorks(state.market?.works||[]);}));
["market-keyword-source","market-keyword-category"].forEach(id=>$("#"+id)?.addEventListener("change",()=>renderMarketKeywords(state.market?.keywords||{})));
$("#market-work-list")?.addEventListener("change",async event=>{
  const select=event.target.closest(".market-length-editor");if(!select)return;
  select.disabled=true;
  try{
    await api(`/api/market/works/${encodeURIComponent(select.dataset.marketWorkId)}/length`,{method:"PUT",body:JSON.stringify({length_type:select.value||null})});
    await loadMarketDashboard();toast("篇幅类型已更新");
  }catch(error){toast(error.message);select.disabled=false;}
});

async function learnReference() {
  if (!state.activeReference) return;
  state.referenceTask={status:"running",phase:"local_learning",started_at:new Date().toISOString(),completed_windows:0,total_windows:0};renderReferenceTaskStatus();
  try { const result=await api(`/api/references/${state.activeReference.id}/learn`,{method:"POST"}); state.learningReport=result; state.mechanisms=await api("/api/learning/mechanisms");state.referenceTask={...state.referenceTask,status:"completed",phase:"completed",finished_at:new Date().toISOString(),completed_windows:result.analyzed_windows,total_windows:result.window_count,summary:`全文覆盖 ${result.coverage_percent}%，整理出 ${result.mechanisms.length} 个候选写法`}; renderReferenceDetail(); renderLearning(); toast(`全文覆盖 ${result.coverage_percent}% · 已提炼 ${result.mechanisms.length} 个候选机制`); }
  catch(error) { state.referenceTask={...state.referenceTask,status:"failed",phase:"failed",finished_at:new Date().toISOString(),error:error.message};renderReferenceTaskStatus();toast(error.message); }
}
async function modelLearnReference() {
  if(!state.activeReference||!confirm("这是什么：模型会逐段阅读全文，先独立查找重要内容，再复核本地候选。\n\n为什么现在询问：这个操作会调用已配置的模型，可能产生费用。\n\n操作后会发生什么：结果会明确标注为模型确认或模型新增，不会自动修改正文或写作项目。\n\n开始模型全文分析？"))return;
  try{
    state.referenceTask=await api(`/api/references/${state.activeReference.id}/model-learn`,{method:"POST"});renderReferenceTaskStatus();
    pollReferenceAnalysisTask(state.activeReference.id);
  }catch(error){state.referenceTask={status:"failed",phase:"failed",started_at:new Date().toISOString(),error:error.message};renderReferenceTaskStatus();toast(error.message);}
}

async function loadProjectLearning() {
  const projectId=$("#learning-project").value;
  if(projectId){
    [state.projectLearning,state.outlines,state.effectiveRules]=await Promise.all([
      api(`/api/projects/${projectId}/learning`),
      api(`/api/projects/${projectId}/learning/outlines`),
      api(`/api/projects/${projectId}/learning/effective-rules`),
    ]);
  }else{
    state.projectLearning=null;state.effectiveRules=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null;
  }
  renderLearningArtifacts();
  renderOutlineWorkspace();
}

function setOutlineOperationStatus(kind,title,detail){
  const shell=$("#outline-operation-status");if(!shell)return;
  shell.className=`outline-operation-status ${kind||""}`.trim();
  shell.innerHTML=`<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail||"")}</span>`;
}

async function loadOutlineWorkspace(){
  const projectId=learningProjectId();
  state.outlines=projectId?await api(`/api/projects/${projectId}/learning/outlines`):null;
  const ids=new Set((state.outlines?.candidates||[]).map(item=>item.id));
  if(!ids.has(state.activeOutlineCandidateId)){state.activeOutlineCandidateId=null;state.outlineComparison=null;}
  renderOutlineWorkspace();
}

function outlineChangeLabel(type){return {added:"新增剧情",removed:"删除剧情",changed:"内容变化",reordered:"位置调整",uncertain:"暂时判断不了"}[type]||"发生变化";}

function renderOutlineComparison(report){
  const shell=$("#outline-comparison");if(!shell)return;
  if(!report){shell.hidden=true;shell.innerHTML="";return;}
  shell.hidden=false;
  const summary=report.summary||{},changes=report.changes||[];
  const risks=(report.risks||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join("");
  const list=changes.length?changes.map(item=>`<article class="outline-change-item">
    <label><input type="checkbox" data-outline-change="${item.id}"> <span><strong>${escapeHtml(item.label)}</strong><small>${outlineChangeLabel(item.type)}</small></span></label>
    <p>${escapeHtml(item.explanation||"请查看前后内容后决定是否采用。")}</p>
    ${item.impact?`<p class="outline-impact"><strong>可能影响：</strong>${escapeHtml(item.impact)}</p>`:""}
    <details><summary>查看改动前后</summary><div class="outline-before-after"><section><span>当前大纲</span><pre>${escapeHtml(item.current_text||"（没有这段）")}</pre></section><section><span>候选大纲</span><pre>${escapeHtml(item.candidate_text||"（将删除这段）")}</pre></section></div></details>
  </article>`).join(""):'<div class="learning-empty"><strong>没有发现变化</strong><p>这个候选与当前大纲内容相同，不需要应用。</p></div>';
  shell.innerHTML=`<header><div><h4>比较结果</h4><p>勾选你想要的变化；没有勾选的内容会保持原样。</p></div><div class="outline-change-summary"><span>新增 <b>${summary.added||0}</b></span><span>删除 <b>${summary.removed||0}</b></span><span>调整 <b>${summary.changed||0}</b></span></div></header>
    ${risks?`<ul class="outline-risks">${risks}</ul>`:""}
    <div class="outline-change-list">${list}</div>
    <footer>
      ${report.semantic_review_recommended?'<button class="secondary" type="button" data-outline-semantic>请模型判断</button>':""}
      <button class="secondary" type="button" data-outline-apply-selected ${changes.length?"":"disabled"}>应用勾选的变化</button>
      <button class="primary" type="button" data-outline-apply-whole ${report.can_apply&&changes.length?"":"disabled"}>整体采用这个版本</button>
    </footer>`;
  shell.querySelector("[data-outline-semantic]")?.addEventListener("click",semanticReviewOutline);
  shell.querySelector("[data-outline-apply-selected]")?.addEventListener("click",()=>applyOutline(false));
  shell.querySelector("[data-outline-apply-whole]")?.addEventListener("click",()=>applyOutline(true));
}

function renderOutlineWorkspace(){
  const currentShell=$("#outline-current"),candidateShell=$("#outline-candidates"),editor=$("#outline-editor");
  if(!currentShell||!candidateShell||!editor)return;
  const current=state.outlines?.current;
  const currentVersion=Number(current?.outline_version)>0?`第 ${current.outline_version} 版`:"旧项目已有版本";
  currentShell.innerHTML=current?.exists
    ?`<strong>当前正式大纲 · ${currentVersion}</strong><span>${escapeHtml(current.message)}</span>`
    :`<strong>还没有正式大纲</strong><span>${escapeHtml(current?.message||"生成候选后，可以把它设为第一版大纲。")}</span>`;
  const candidates=state.outlines?.candidates||[];
  candidateShell.innerHTML=candidates.length?candidates.map(item=>`<button type="button" class="outline-candidate-item ${item.id===state.activeOutlineCandidateId?"active":""}" data-outline-open="${item.id}"><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.message||"等待你处理")}</small></span><b>查看并编辑全文</b></button>`).join(""):'<div class="learning-empty"><strong>还没有候选大纲</strong><p>在上方说明想调整什么，然后生成候选版本。</p></div>';
  candidateShell.querySelectorAll("[data-outline-open]").forEach(button=>button.addEventListener("click",()=>{
    state.activeOutlineCandidateId=button.dataset.outlineOpen;state.outlineComparison=null;renderOutlineWorkspace();
  }));
  const candidate=candidates.find(item=>item.id===state.activeOutlineCandidateId);
  editor.hidden=!candidate;
  if(candidate){
    $("#outline-editor-title").value=candidate.title||"候选大纲";
    $("#outline-editor-content").value=candidate.content||"";
  }
  renderOutlineComparison(candidate?state.outlineComparison:null);
  const history=state.outlines?.history||[];
  $("#outline-history-count").textContent=`${history.length} 个版本`;
  $("#outline-history-list").innerHTML=history.length?history.slice().reverse().map(item=>`<div class="outline-history-item"><span><strong>第 ${item.outline_version} 版${item.is_current?" · 当前":""}</strong><small>${escapeHtml(item.source==="restored"?"从历史恢复":"由候选大纲确认")}</small></span><button class="secondary" type="button" data-outline-restore="${item.outline_version}" ${item.is_current?"disabled":""}>恢复这个版本</button></div>`).join(""):'<p class="skill-meta">还没有正式大纲版本</p>';
  $("#outline-history-list").querySelectorAll("[data-outline-restore]").forEach(button=>button.addEventListener("click",()=>restoreOutline(Number(button.dataset.outlineRestore))));
}

async function saveOutlineCandidate(){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId;if(!projectId||!candidateId)return;
  setOutlineOperationStatus("busy","正在保存修改","保存完成后会重新读取候选全文。");
  try{
    await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}`,{method:"PUT",body:JSON.stringify({title:$("#outline-editor-title").value,outline:$("#outline-editor-content").value})});
    state.outlineComparison=null;await loadOutlineWorkspace();setOutlineOperationStatus("success","修改已保存","现在可以比较它与正式大纲的变化。");
  }catch(error){setOutlineOperationStatus("error","保存失败",error.message);}
}

async function compareOutlineCandidate(){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId;if(!projectId||!candidateId)return;
  setOutlineOperationStatus("busy","正在本地比较","只比较大纲文字和结构，不会调用模型。");
  try{
    await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}`,{method:"PUT",body:JSON.stringify({title:$("#outline-editor-title").value,outline:$("#outline-editor-content").value})});
    state.outlineComparison=await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}/comparison`);renderOutlineWorkspace();
    setOutlineOperationStatus("success","比较完成","请勾选想采用的变化，或整体采用候选版本。");
  }catch(error){setOutlineOperationStatus("error","比较失败",error.message);}
}

async function semanticReviewOutline(){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId;if(!projectId||!candidateId)return;
  setOutlineOperationStatus("busy","正在请模型判断","只发送本地无法确定的变化，不会发送或改写正文。");
  try{
    state.outlineComparison=await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}/semantic-review`,{method:"POST"});renderOutlineWorkspace();
    setOutlineOperationStatus("success","模型判断完成","判断已放回变化列表，请继续选择是否应用。");
  }catch(error){setOutlineOperationStatus("error","模型判断失败",error.message);}
}

async function applyOutline(whole){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId,report=state.outlineComparison;if(!projectId||!candidateId||!report)return;
  const changeIds=[...document.querySelectorAll("[data-outline-change]:checked")].map(item=>item.dataset.outlineChange);
  if(!whole&&!changeIds.length)return setOutlineOperationStatus("error","还没有勾选变化","请先勾选至少一项想采用的变化。");
  const manuscript=Boolean(report.current?.manuscript_exists);
  const message=whole?(manuscript?"整体采用会改变后续创作依据，但不会修改已经写好的正文。确认继续？":"整体采用这个候选版本作为正式大纲？"):`应用勾选的 ${changeIds.length} 项变化？其他内容保持不变。`;
  if(!confirm(message))return;
  setOutlineOperationStatus("busy","正在应用大纲","系统正在保存新版本并检查锁定设定。");
  try{
    await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}/apply`,{method:"POST",body:JSON.stringify({expected_revision:report.state_revision,apply_whole:whole,change_ids:whole?null:changeIds,confirm_manuscript_impact:whole&&manuscript})});
    state.activeOutlineCandidateId=null;state.outlineComparison=null;await loadProjectLearning();
    setOutlineOperationStatus("success","新大纲已生效","后续创作会使用它；已经写好的正文没有改变。");
  }catch(error){setOutlineOperationStatus("error","应用失败",error.message);}
}

async function discardOutlineCandidate(){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId;if(!projectId||!candidateId||!confirm("放弃这个候选大纲？正式大纲和正文都不会改变。"))return;
  setOutlineOperationStatus("busy","正在放弃候选","请稍候。");
  try{await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}`,{method:"DELETE"});state.activeOutlineCandidateId=null;state.outlineComparison=null;await loadOutlineWorkspace();setOutlineOperationStatus("success","候选已放弃","正式大纲和正文都没有改变。");}
  catch(error){setOutlineOperationStatus("error","放弃失败",error.message);}
}

async function restoreOutline(version){
  const projectId=learningProjectId();if(!projectId||!confirm(`恢复第 ${version} 版大纲？系统会新增一个恢复版本，现有历史和正文都不会删除。`))return;
  setOutlineOperationStatus("busy","正在恢复历史版本","系统正在创建新的正式大纲版本。");
  try{await api(`/api/projects/${projectId}/learning/outlines/restore`,{method:"POST",body:JSON.stringify({outline_version:version})});await loadProjectLearning();setOutlineOperationStatus("success","历史版本已恢复","它已成为新的正式大纲，原历史仍然保留。");}
  catch(error){setOutlineOperationStatus("error","恢复失败",error.message);}
}

function mechanismStage(position){
  const value=Number(position);
  if(value<=10)return "开头";
  if(value<=30)return "前段";
  if(value<=70)return "中段";
  if(value<=90)return "后段";
  return "结尾";
}

function mechanismEvidenceGroups(item){
  const positions=item.data.positions||[],groups={};
  (item.evidence||[]).forEach((evidence,index)=>{
    const stage=mechanismStage(positions[index]??50);
    (groups[stage]??=[]).push(evidence);
  });
  return groups;
}

function mechanismSourceMeta(item){
  const analysis=item.analysis||{},origin=item.data.analysis_origin||"local";
  const values={
    local_only:{label:"本地提炼",detail:"未调用模型",judgment:"等待模型判断",tone:"local"},
    model_only:{label:"模型新增",detail:"模型全文分析",judgment:"等待你确认",tone:"model"},
    model_confirmed:{label:"本地发现 + 模型确认",detail:"模型全文分析",judgment:"较高",tone:"confirmed"},
    model_disagrees:{label:"本地与模型意见不同",detail:"需要你判断",judgment:"意见不同",tone:"conflict"},
    needs_review:{label:"本地 + 模型复核",detail:"模型暂时无法确定",judgment:"待复核",tone:"uncertain"},
  };
  return {...(values[analysis.state]||values[origin==="model"?"model_only":"local_only"]),origin,analysis};
}

function renderMechanismCard(item,adopted,rejectedView){
  const rejected=item.status==="rejected",confirmed=item.status==="confirmed";
  const needsConfirm=Number(item.data.confidence||0)<0.7&&!confirmed;
  const statusLabel=rejected?"已拒绝":confirmed?"已确认":"等待你判断";
  const source=mechanismSourceMeta(item),modelOnly=source.origin==="model";
  const text=(value,fallback)=>modelOnly?readableModelText(value,fallback):String(value||fallback);
  const evidence=item.evidence||[],positions=item.data.positions||[];
  const stages=[...new Set(positions.map(mechanismStage))];
  const groups=mechanismEvidenceGroups(item);
  const conditions=text((item.data.incompatible_conditions||[]).join("；"),"没有明确使用条件，请结合原文证据判断是否适合。 ");
  const modeLabels={short:"短篇",long:"长篇"};
  const modes=(item.data.applicable_modes||[]).map(value=>modeLabels[value]||value);
  const applicableStages=item.data.applicable_stages||[];
  const genres=item.data.applicable_genres||[];
  const scope=[modes.length?modes.join("、"):"短篇和长篇",applicableStages.length?applicableStages.join("、"):null,genres.length?genres.join("、"):null].filter(Boolean).join(" · ");
  const similar=(item.similar_items||[]).length?`<p class="mechanism-similar">发现意思相近的写法：${item.similar_items.slice(0,2).map(value=>escapeHtml(value.name)).join("、")}。应用前建议只保留表达最清楚的一条。</p>`:"";
  const groupedEvidence=Object.entries(groups).map(([stage,items])=>`<section><strong>${stage} · ${items.length} 处</strong>${items.map(value=>`<blockquote class="mechanism-evidence">${escapeHtml(value.excerpt)}</blockquote>`).join("")}</section>`).join("");
  const deletable=item.deletable!==false;
  const selection=rejectedView&&deletable?`<label class="mechanism-select"><input type="checkbox" data-mechanism-select="${item.id}"> 选择</label>`:"";
  const rejectedActions=deletable?`<button class="secondary danger-text" data-mechanism-delete="${item.id}">永久删除</button>`:`<p class="mechanism-delete-blocked">${escapeHtml(item.delete_reason||"这条写法当前不能删除")}</p><button class="secondary" data-mechanism-release="${item.id}">从作品中移除</button>`;
  const activeActions=`<button class="secondary" data-mechanism-confirm="${item.id}" ${confirmed?"disabled":""}>${confirmed?"已保留":"保留为候选"}</button><button class="primary" data-mechanism-adopt="${item.id}" ${(adopted.has(item.id)||needsConfirm)?"disabled":""}>${adopted.has(item.id)?"已应用":"应用到当前作品"}</button><button class="secondary" data-mechanism-reject="${item.id}">不采用</button>`;
  const decision=rejected?"这条写法已被你拒绝。可以永久删除；如果仍在作品中使用，需要先取消应用。":"“保留为候选”表示认可分析；“应用到当前作品”会写入创作蓝图，但不会直接修改正文。";
  const modelReason=source.analysis.model?readableModelText(source.analysis.model.reason,"模型完成了复核，但没有提供可读的中文理由。 "):"";
  const localScore=source.analysis.local?.confidence;
  const technical=`<details class="mechanism-judgment-details"><summary>查看判断依据</summary><p>本地判断：${localScore==null?"未运行":`${Math.round(Number(localScore)*100)}%`} · 模型复核：${source.analysis.model?source.detail:"未调用模型"}</p>${modelReason?`<p>模型理由：${escapeHtml(modelReason)}</p>`:""}<p>分析时间：${escapeHtml(formatLocalTimestamp(item.updated_at)||"未记录")}</p></details>`;
  return `<article class="mechanism-item">${selection}<div class="mechanism-source-badges"><span class="${source.tone}">${source.label}</span><span>${source.detail}</span></div><header><div><h3>${escapeHtml(text(item.data.name,"模型提取的候选写法"))}</h3><span class="mechanism-status">${statusLabel}</span></div><div class="mechanism-stage-summary"><strong>来源资料：${escapeHtml(source.analysis.source_title||"未记录")}</strong><span>证据 ${evidence.length||positions.length||1} 处</span><span>适合：${escapeHtml(scope)}</span><span>综合判断：${source.judgment}</span></div></header>${similar}<details class="mechanism-details"><summary>查看详情 · 写法和原文依据</summary><div class="mechanism-explanation"><section><span>它能起什么作用 · 为什么值得学习</span><p>${escapeHtml(text(item.data.interpretation||item.data.emotional_effect,"它可能影响读者对信息、人物或情节推进的感受。"))}</p></section><section><span>什么时候适合使用</span><p>${escapeHtml(scope)}</p></section><section><span>具体怎么使用 · 你的作品可以怎么用</span><p>${escapeHtml(text(item.data.transfer_guidance,"保留这种写法的作用，替换人物、设定、情节和具体表达。"))}</p></section><section><span>什么时候不要用</span><p>${escapeHtml(conditions)}</p></section></div>${evidence[0]?`<section class="mechanism-representative"><span>原文是怎么写的 · 来自《${escapeHtml(source.analysis.source_title||"未记录")}》</span><blockquote class="mechanism-evidence">${escapeHtml(evidence[0].excerpt)}</blockquote></section>`:""}${evidence.length>1?`<details class="mechanism-evidence-list"><summary>查看全部证据（${evidence.length} 处）</summary>${groupedEvidence}</details>`:""}${technical}<p class="mechanism-decision"><strong>${rejected?"当前状态：":"你需要决定："}</strong>${decision}</p></details><div class="mechanism-actions">${rejected?rejectedActions:activeActions}</div></article>`;
}

function renderLearning() {
  const select=$("#learning-project"); if (!select) return;
  select.innerHTML=state.projects.length ? state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("") : '<option value="">请先创建作品</option>';
  if (state.activeProject) select.value=state.activeProject.id;
  const adopted=new Set((state.projectLearning?.adoptions||[]).map(item=>item.node_id));
  const rejectedView=$("#learning-mechanism-view")?.value==="rejected";
  const origin=$("#learning-mechanism-origin")?.value||"all";
  const visible=state.mechanisms.filter(item=>origin==="all"||(item.data.analysis_origin||"local")===origin);
  const deletableCount=visible.filter(item=>item.deletable!==false).length;
  const batch=rejectedView&&deletableCount?`<div class="mechanism-batch-actions"><label><input type="checkbox" data-mechanism-select-all> 全选可删除的 ${deletableCount} 条</label><button class="secondary danger-text" data-mechanism-delete-selected>删除所选</button></div>`:"";
  const cards=visible.length?visible.map(item=>renderMechanismCard(item,adopted,rejectedView)).join(""):`<p class="skill-meta">${rejectedView?"当前筛选下没有已拒绝写法":"当前筛选下没有候选写法"}</p>`;
  $("#learning-mechanisms").innerHTML=batch+cards;
  document.querySelectorAll("[data-mechanism-confirm]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismConfirm,"confirm")));
  document.querySelectorAll("[data-mechanism-adopt]").forEach(button=>button.addEventListener("click",()=>adoptMechanism(button.dataset.mechanismAdopt)));
  document.querySelectorAll("[data-mechanism-reject]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismReject,"reject")));
  document.querySelectorAll("[data-mechanism-delete]").forEach(button=>button.addEventListener("click",()=>deleteRejectedMechanisms([button.dataset.mechanismDelete])));
  document.querySelectorAll("[data-mechanism-release]").forEach(button=>button.addEventListener("click",()=>releaseMechanism(button.dataset.mechanismRelease)));
  $("[data-mechanism-delete-selected]")?.addEventListener("click",()=>deleteRejectedMechanisms([...document.querySelectorAll("[data-mechanism-select]:checked")].map(item=>item.dataset.mechanismSelect)));
  $("[data-mechanism-select-all]")?.addEventListener("change",event=>document.querySelectorAll("[data-mechanism-select]").forEach(item=>item.checked=event.target.checked));
  if (select.value && !state.projectLearning) loadProjectLearning(); else renderLearningArtifacts();
}
const mechanismView=()=>$("#learning-mechanism-view")?.value||"active";
async function reloadMechanisms(){state.mechanisms=await api(`/api/learning/mechanisms?view=${encodeURIComponent(mechanismView())}`);renderLearning();}
async function reviseMechanism(id,action) { try { await api(`/api/learning/nodes/${id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})}); await reloadMechanisms(); toast(action==="confirm"?"分析已确认":"分析已拒绝，可在“已拒绝”中查看"); } catch(error){toast(error.message);} }
async function deleteRejectedMechanisms(ids){if(!ids.length)return toast("请先选择要删除的记录");if(!confirm(`永久删除 ${ids.length} 条已拒绝机制及其证据？此操作不可撤销。`))return;try{const result=await api("/api/learning/mechanisms",{method:"DELETE",body:JSON.stringify({node_ids:ids})});await reloadMechanisms();const skipped=result.skipped.length?`；未删除：${result.skipped.map(item=>item.reason).join("；")}`:"";toast(`已删除 ${result.deleted_ids.length} 条${skipped}`);}catch(error){toast(error.message);}}
async function releaseMechanism(id){const item=state.mechanisms.find(value=>value.id===id);const projectIds=item?.active_project_ids||[];if(!projectIds.length)return reloadMechanisms();if(!confirm(`这条写法仍在 ${projectIds.length} 个作品中使用。确认从这些作品的创作蓝图中移除？不会修改已经生成的正文。`))return;try{for(const projectId of projectIds)await api(`/api/projects/${projectId}/learning/rejections/${id}`,{method:"POST",body:JSON.stringify({reason:"用户从已拒绝列表中取消应用"})});state.projectLearning=null;await reloadMechanisms();toast("已从作品中移除，现在可以永久删除");}catch(error){toast(error.message);}}
async function adoptMechanism(id) { const projectId=$("#learning-project").value; if(!projectId)return toast("请先选择作品"); try { await api(`/api/projects/${projectId}/learning/adoptions/${id}`,{method:"POST",body:JSON.stringify({edits:{}})}); await loadProjectLearning(); renderLearning(); toast("已采纳并生成新版创作蓝图"); } catch(error){toast(error.message);} }
function effectiveRulesMarkup(data,compact=false){
  if(!data)return '<p class="skill-meta">尚未读取当前作品的创作设置</p>';
  const layers=(data.layers||[]).map(item=>`<li><b>${item.priority}</b><span><strong>${escapeHtml(item.name)}</strong><small>${Number(item.count||0)} 项 · ${escapeHtml(item.status)}</small></span></li>`).join("");
  const conflicts=data.conflicts||[];
  const cautions=data.cautions||[];
  const warnings=conflicts.length?`<div class="effective-rule-warning"><strong>需要你留意 ${conflicts.length} 项</strong>${conflicts.map(item=>`<p>${escapeHtml(item.message)}</p>`).join("")}</div>`:'<div class="effective-rule-clear"><strong>没有发现明确冲突</strong><span>生成时会按下方顺序使用。</span></div>';
  const usage=data.usage||[];
  const usageLabels={evident:"明显体现",partial:"有部分迹象",missing:"没有发现",review:"需要人工判断"};
  const usageHtml=usage.length?`<details class="effective-rule-usage"><summary>检查已有正文是否体现补充写法（${usage.length}条）</summary>${usage.map(item=>`<p><strong>${escapeHtml(item.name)}</strong><span class="${item.status}">${usageLabels[item.status]||"等待判断"}</span><small>${escapeHtml(item.reason)}</small></p>`).join("")}</details>`:(data.has_manuscript?'<p class="skill-meta">当前没有需要检查的补充写法。</p>':'<p class="skill-meta">生成正文后，这里会用本地规则检查补充写法是否得到体现。</p>');
  const cautionHtml=cautions.length&&!compact?`<details class="effective-rule-cautions"><summary>查看不适用情况（${cautions.length}项）</summary>${cautions.map(item=>`<p><strong>${escapeHtml(item.name)}</strong>${escapeHtml(item.message)}</p>`).join("")}</details>`:"";
  const migration=data.legacy_style?'<span>已迁移旧范文笔感，原文件仍然保留。</span>':"";
  return `<div class="effective-rule-head"><div><strong>当前共 ${data.layers.length} 层创作要求</strong><span>${escapeHtml(data.priority_note)}</span>${migration}</div>${warnings}</div><ol class="effective-rule-layers">${layers||'<li><span><strong>尚未设置创作规则</strong><small>可以继续使用原有创建方式</small></span></li>'}</ol>${usageHtml}${cautionHtml}`;
}
function renderEffectiveRules(){const shell=$("#learning-effective-rules");if(shell)shell.innerHTML=effectiveRulesMarkup(state.effectiveRules);}
async function removeAdoption(nodeId){
  const projectId=learningProjectId();if(!projectId||!confirm("从当前作品移除这条补充写法？学习库和已有正文不会改变。"))return;
  try{await api(`/api/projects/${projectId}/learning/rejections/${nodeId}`,{method:"POST",body:JSON.stringify({reason:"用户从创作蓝图移除"})});await loadProjectLearning();renderLearning();toast("已从当前作品移除，创作蓝图已更新");}catch(error){toast(error.message);}
}
function renderCreativeBlueprint(item){
  const adoptions=state.projectLearning?.adoptions||[];
  const rows=adoptions.length?adoptions.map(value=>`<article class="blueprint-rule-row"><div><strong>${escapeHtml(value.data.name||"剧情吸引力规则")}</strong><span>来自《${escapeHtml(value.source_title||"未记录")}》</span></div><button class="secondary danger-text" type="button" data-blueprint-remove="${value.node_id}">从当前作品移除</button></article>`).join(""):'<p class="skill-meta">当前没有补充写法，原有文笔规则仍然生效。</p>';
  return `<details class="learning-artifact"><summary><span><strong>创作蓝图</strong><small>${adoptions.length} 条补充写法</small></span><b>${item.status==="stale"?"待复核":"生效中"}</b></summary><div class="blueprint-rule-list">${rows}</div><p class="artifact-boundary">这里的写法负责剧情安排，不会改写基础文笔规则或已有正文。</p></details>`;
}
function renderLearningArtifact(item){
  if(item.artifact_type==="creative_blueprint")return renderCreativeBlueprint(item);
  const canRestore=item.version>1&&["prose_baseline","voice_profiles","epistemic_state"].includes(item.artifact_type);
  return `<details class="learning-artifact"><summary><span><strong>${escapeHtml(learningArtifactLabels[item.artifact_type]||"学习资料")}</strong><small>${artifactSummary(item)}</small></span><b>${item.status==="stale"?"待复核":"生效中"}</b></summary><div class="project-learning-copy">${readableLearningValue(item.data)}</div>${canRestore?`<div class="artifact-version-actions"><button class="secondary" type="button" data-artifact-history="${item.artifact_type}">查看和恢复旧版本</button><div data-artifact-history-list="${item.artifact_type}"></div></div>`:""}</details>`;
}
function renderLearningArtifacts(){
  const shell=$("#learning-artifacts"); if(!shell)return;
  const artifacts=state.projectLearning?.artifacts||[];
  const reviews=state.projectLearning?.adoption_reviews||[];
  const warning=reviews.length?`<section class="learning-review-alert"><div class="learning-review-list">${reviews.map(renderLearningReview).join("")}</div></section>`:"";
  const content=artifacts.length?artifacts.map(renderLearningArtifact).join(""):'<div class="learning-empty"><strong>当前作品还没有应用任何写法</strong><p>在“候选写法”中确认并应用后，这里会展示真正生效的创作规则。</p></div>';
  shell.innerHTML=warning+content;
  renderEffectiveRules();
  shell.querySelectorAll("[data-learning-review-keep]").forEach(button=>button.addEventListener("click",()=>keepLearningReview(button.dataset.learningReviewKeep)));
  shell.querySelectorAll("[data-learning-review-remove]").forEach(button=>button.addEventListener("click",()=>removeLearningReview(button.dataset.learningReviewRemove)));
  shell.querySelectorAll("[data-blueprint-remove]").forEach(button=>button.addEventListener("click",()=>removeAdoption(button.dataset.blueprintRemove)));
  shell.querySelectorAll("[data-artifact-history]").forEach(button=>button.addEventListener("click",()=>loadArtifactHistory(button.dataset.artifactHistory)));
}
async function loadArtifactHistory(type){
  const projectId=learningProjectId(),shell=document.querySelector(`[data-artifact-history-list="${type}"]`);if(!projectId||!shell)return;
  shell.innerHTML='<p class="skill-meta">正在读取历史版本…</p>';
  try{const history=await api(`/api/projects/${projectId}/learning/artifacts/${type}/history`);const latest=history[0]?.version;shell.innerHTML=history.map(item=>`<div class="artifact-history-row"><span><strong>版本 ${item.version}${item.version===latest?" · 当前":""}</strong><small>${escapeHtml(formatLocalTimestamp(item.created_at)||"时间未记录")}</small></span><button class="secondary" type="button" data-artifact-restore="${item.version}" ${item.version===latest?"disabled":""}>恢复这个版本</button></div>`).join("");shell.querySelectorAll("[data-artifact-restore]").forEach(button=>button.addEventListener("click",()=>restoreArtifact(type,Number(button.dataset.artifactRestore))));}catch(error){shell.innerHTML=`<p class="error-text">读取失败：${escapeHtml(error.message)}</p>`;}
}
async function restoreArtifact(type,version){
  const projectId=learningProjectId();if(!projectId||!confirm(`恢复版本 ${version}？系统会新增一个恢复版本，已有正文不会改变。`))return;
  try{await api(`/api/projects/${projectId}/learning/artifacts/${type}/restore`,{method:"POST",body:JSON.stringify({version})});await loadProjectLearning();renderLearning();toast("旧版本已恢复并开始用于后续创作");}catch(error){toast(error.message);}
}
function learningReviewItems(review){
  const data=review.data||{};
  const items=[];
  if(data.opening_rule)items.push(["开头设计",data.opening_rule]);
  (data.cycle_rules||[]).forEach((value,index)=>items.push([`第 ${index+1} 轮推进`,value]));
  (data.question_rules||[]).forEach(value=>items.push(["问题链",value]));
  (data.relationship_rules||[]).forEach(value=>items.push(["关系变化",value]));
  if(data.reversal_rule)items.push(["反转",data.reversal_rule]);
  if(data.ending_rule)items.push(["结局",data.ending_rule]);
  if(!items.length&&data.transfer_guidance)items.push(["使用方法",data.transfer_guidance]);
  if(!items.length&&review.mechanism?.transfer_guidance)items.push(["使用方法",review.mechanism.transfer_guidance]);
  return items;
}
function renderLearningReview(review){
  const title=review.mechanism?.name||(review.data?.mechanism_type==="attraction_guidance"?"剧情吸引力规则":"已采用的写法");
  const items=learningReviewItems(review);
  const ruleCount=items.length;
  const rules=ruleCount?items.map(([label,value])=>`<div><span>${escapeHtml(label)}</span><p>${escapeHtml(value)}</p></div>`).join(""):'<p class="skill-meta">没有找到可读摘要，请在下方创作蓝图中查看。</p>';
  return `<article class="learning-review-item"><header><div><strong>${escapeHtml(title)}</strong><span>需要你确认</span></div><small>仍在当前作品中使用</small></header><p class="learning-review-reason">来源资料的分类变了，请决定是否继续用于新创作。已生成的正文不会改变。</p><footer class="learning-review-actions"><button class="primary" data-learning-review-keep="${review.node_id}">继续使用</button><button class="secondary danger-text" data-learning-review-remove="${review.node_id}">从作品移除</button></footer><details class="learning-review-details"><summary>查看具体规则${ruleCount?`（${ruleCount} 条）`:""}</summary><div class="learning-review-rules">${rules}</div></details></article>`;
}
async function keepLearningReview(nodeId){const projectId=learningProjectId();if(!projectId||!confirm("继续使用这项内容？系统会按当前资料分类重新启用它，不会修改已经生成的正文。"))return;try{await api(`/api/projects/${projectId}/learning/adoptions/${nodeId}`,{method:"POST",body:JSON.stringify({edits:{}})});await loadProjectLearning();renderLearning();toast("已确认继续使用");}catch(error){toast(error.message);}}
async function removeLearningReview(nodeId){const projectId=learningProjectId();if(!projectId||!confirm("从当前作品移除这项内容？创作蓝图会同步更新，但不会修改已经生成的正文。"))return;try{await api(`/api/projects/${projectId}/learning/rejections/${nodeId}`,{method:"POST",body:JSON.stringify({reason:"用户在作品应用复核中移除"})});await loadProjectLearning();renderLearning();toast("已从当前作品移除");}catch(error){toast(error.message);}}
function switchLearningView(view){
  const target=["references","mechanisms","application"].includes(view)?view:"references";
  document.querySelectorAll("[data-learning-view]").forEach(button=>button.classList.toggle("active",button.dataset.learningView===target));
  document.querySelectorAll("[data-learning-panel]").forEach(panel=>{const active=panel.dataset.learningPanel===target;panel.hidden=!active;panel.classList.toggle("active",active);});
}
document.querySelectorAll("[data-learning-view]").forEach(button=>button.addEventListener("click",()=>switchLearningView(button.dataset.learningView)));
$("#learning-project").addEventListener("change",async event=>{ state.activeProject=state.projects.find(item=>item.id===event.target.value)||state.activeProject; state.projectLearning=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null; await loadProjectLearning(); renderLearning(); });
$("#learning-mechanism-view").addEventListener("change",reloadMechanisms);
$("#learning-mechanism-origin").addEventListener("change",renderLearning);
const learningProjectId=()=>$("#learning-project").value;
async function saveLearningArtifact(path,data){const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/${path}`,{method:"PUT",body:JSON.stringify({data})});await loadProjectLearning();toast("已保存为新版本");}catch(error){toast(error.message);}}
$("#baseline-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);await saveLearningArtifact("prose-baseline",{dialogue:form.get("dialogue"),psychology:form.get("psychology"),forbidden_patterns:String(form.get("forbidden")||"").split(/\r?\n/).map(item=>item.trim()).filter(Boolean)});});
$("#voice-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);const current=state.projectLearning?.artifacts?.find(item=>item.artifact_type==="voice_profiles")?.data||{};await saveLearningArtifact("voice-profiles",{...current,[form.get("name")]:{rules:form.get("profile")}});});
$("#scene-brief-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/scene-briefs`,{method:"POST",body:JSON.stringify({outline:new FormData(event.target).get("outline")})});await loadProjectLearning();toast("场景简报已生成，可继续编辑");}catch(error){toast(error.message);}});
$("#outline-generate-form").addEventListener("submit",async event=>{
  event.preventDefault();const projectId=learningProjectId();if(!projectId)return setOutlineOperationStatus("error","还没有选择作品","请先在页面顶部选择要处理的作品。");
  if(!confirm("生成候选会调用规划模型，可能产生费用。结果只进入候选区，不会覆盖正式大纲或正文。继续？"))return;
  const button=event.currentTarget.querySelector("button");button.disabled=true;setOutlineOperationStatus("busy","正在生成候选大纲","规划模型正在整理新版本，完成前请不要重复点击。");
  try{await api(`/api/projects/${projectId}/learning/generate-outline`,{method:"POST",body:JSON.stringify({brief:new FormData(event.currentTarget).get("brief")})});await loadOutlineWorkspace();setOutlineOperationStatus("success","候选大纲已生成","请在下方打开全文，编辑或比较后再决定是否应用。");}
  catch(error){setOutlineOperationStatus("error","生成失败",error.message);}
  finally{button.disabled=false;}
});
$("#outline-save").addEventListener("click",saveOutlineCandidate);
$("#outline-compare").addEventListener("click",compareOutlineCandidate);
$("#outline-discard").addEventListener("click",discardOutlineCandidate);
$("#line-edit-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId||!confirm("将调用精修模型生成候选文本，不会修改正式正文。继续？"))return;const form=new FormData(event.target);try{const result=await api(`/api/projects/${projectId}/learning/model-line-edit`,{method:"POST",body:JSON.stringify({source:form.get("source"),issues:String(form.get("issues")).split(/[,，]/).map(item=>item.trim()).filter(Boolean),locked_facts:[],adjacent_context:""})});const shell=$("#line-edit-result");shell.hidden=false;shell.textContent=result.candidate;toast("精修候选已生成，原文未修改");}catch(error){toast(error.message);}});

function renderNlpStatus(){ if(!state.localNlp)return; $("#nlp-status").textContent=`${state.localNlp.installed?"已安装":"未安装"} · ${state.localNlp.enabled?"已启用":"未启用"} · ${state.localNlp.operation} · ${state.localNlp.download_notice}`; $("#nlp-toggle").textContent=state.localNlp.enabled?"停用":"启用"; }
async function nlpAction(path,options={method:"POST"}){ try{state.localNlp=await api(path,options);renderNlpStatus();toast("本地 NLP 状态已更新");}catch(error){toast(error.message);} }
$("#nlp-install").addEventListener("click",()=>nlpAction("/api/settings/local-nlp/install"));
$("#nlp-uninstall").addEventListener("click",()=>confirm("卸载本地中文分析组件？")&&nlpAction("/api/settings/local-nlp/uninstall"));
$("#nlp-toggle").addEventListener("click",()=>nlpAction("/api/settings/local-nlp",{method:"PUT",body:JSON.stringify({enabled:!state.localNlp?.enabled})}));
async function loadWorkflowAnalysis(){
  const shell=$("#workflow-analysis-status"),button=$("#workflow-analysis-toggle");
  if(!state.activeProject){state.workflowAnalysis=null;shell.textContent="请选择作品";button.disabled=true;return;}
  state.workflowAnalysis=await api(`/api/projects/${state.activeProject.id}/learning/workflow-analysis`);
  button.disabled=false;button.textContent=state.workflowAnalysis.enabled?"停用当前作品优化":"为当前作品启用";
  shell.textContent=state.workflowAnalysis.enabled?"已启用 · 首次全文终审，返修后关联窗口复核 · 原创检查仅限本地资料库":"未启用 · 继续使用每轮全文终审";
}
$("#workflow-analysis-toggle").addEventListener("click",async()=>{
  if(!state.activeProject)return toast("请先选择作品");
  state.workflowAnalysis=await api(`/api/projects/${state.activeProject.id}/learning/workflow-analysis`,{method:"PUT",body:JSON.stringify({enabled:!state.workflowAnalysis?.enabled})});
  await loadWorkflowAnalysis();toast("作品分析流程已更新");
});
function renderProjects() {
  const select = $("#active-project");
  select.innerHTML = state.projects.length ? state.projects.map(p => `<option value="${p.id}">${escapeHtml(p.title)}</option>`).join("") : '<option value="">尚无作品</option>';
  if (!state.activeProject || !state.projects.some(p => p.id === state.activeProject.id)) state.activeProject = state.projects[0] || null;
  if (state.activeProject) select.value = state.activeProject.id;
  const materialsSelect = $("#materials-project");
  materialsSelect.innerHTML = select.innerHTML;
  if (state.activeProject) materialsSelect.value = state.activeProject.id;
  $("#project-list").innerHTML = state.projects.length ? state.projects.map(p => `<article class="project-item"><h3>${escapeHtml(p.title)}</h3><div class="skill-meta">${p.mode === "short" ? "短篇" : "长篇"} · ${escapeHtml(p.genre)} · ${Number(p.target_words).toLocaleString()} 字</div><div class="project-actions"><button class="secondary" data-continue="${p.id}">继续写作</button><button class="secondary danger-text" data-trash="${p.id}">移入回收站</button></div></article>`).join("") : '<p class="skill-meta">尚无作品</p>';
  document.querySelectorAll("[data-continue]").forEach(button => button.addEventListener("click", () => continueProject(button.dataset.continue)));
  document.querySelectorAll("[data-trash]").forEach(button => button.addEventListener("click", () => trashProject(button.dataset.trash)));
  renderActiveProject();
}
async function continueProject(projectId) {
  const project = state.projects.find(item => item.id === projectId);
  if (!project) return toast("作品不存在");
  state.activeProject = project;
  renderProjects();
  showView("workbench");
  await renderActiveProject();
  if (project.mode !== "short") return;
  const runs = await api(`/api/projects/${project.id}/runs`);
  const resumableRun = runs.find(item => item.workflow === "short-story"
    && ["failed","cancelled"].includes(item.status));
  if (!resumableRun) return toast("没有可继续的失败任务");
  await run(`/api/runs/${resumableRun.id}/resume`);
}
async function loadProjectLocations(projectId) {
  const shell = $("#project-locations");
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/locations`);
    if (state.activeProject?.id !== projectId) return;
    shell.innerHTML = result.locations.map(item => `<div class="location-row"><div class="location-copy"><strong>${escapeHtml(item.label)}</strong><code>${item.exists ? escapeHtml(item.path) : "尚未生成"}</code></div><div class="location-actions">${item.exists ? `<button class="icon-button small" data-copy-path="${escapeHtml(item.path)}" title="复制路径" aria-label="复制${escapeHtml(item.label)}路径">⧉</button><button class="icon-button small" data-open-location="${escapeHtml(item.kind)}" title="在资源管理器中打开" aria-label="打开${escapeHtml(item.label)}">↗</button>` : ""}</div></div>`).join("");
    shell.querySelectorAll("[data-copy-path]").forEach(button => button.addEventListener("click", async () => {
      try { await navigator.clipboard.writeText(button.dataset.copyPath); toast("路径已复制"); }
      catch(error) { toast(`复制失败：${error.message}`); }
    }));
    shell.querySelectorAll("[data-open-location]").forEach(button => button.addEventListener("click", async () => {
      try { await api(`/api/projects/${projectId}/locations/${button.dataset.openLocation}/open`, {method:"POST"}); }
      catch(error) { toast(error.message); }
    }));
  } catch(error) {
    shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`;
  }
}
function qualityScore(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(1).replace(/\.0$/,"") : "待终审";
}
function qualityIssueStatus(value) {
  return ({resolved:"已解决",closed:"已解决",partially_resolved:"部分解决",uncertain:"需要复核",unresolved:"待处理",open:"待处理"})[value]||"待处理";
}
function qualitySeverity(value) {
  return ({critical:"必须处理",blocking:"必须处理",major:"优先处理",high:"优先处理",medium:"建议处理",low:"可选优化"})[value]||"建议处理";
}
function setCandidateOperationStatus(kind,title,detail="") {
  const shell=$("#candidate-operation-status");
  shell.className=`operation-status ${kind}`;
  shell.innerHTML=`<strong>${escapeHtml(title)}</strong>${detail?`<span>${escapeHtml(detail)}</span>`:""}`;
}
async function loadCandidateQualityControls(projectId) {
  const paths=[
    `/api/projects/${projectId}/quality-references`,
    `/api/projects/${projectId}/quality-references/recommendations`,
    `/api/projects/${projectId}/quality-references/history`,
    `/api/projects/${projectId}/passage-protections`,
  ];
  const results=await Promise.allSettled(paths.map(path=>api(path)));
  const value=index=>results[index].status==="fulfilled"?results[index].value:null;
  return {group:value(0),recommendations:value(1),history:value(2),protections:value(3),hasError:results.some(item=>item.status==="rejected")};
}
function qualityIssuesMarkup(issues) {
  if(!issues.length)return '<div class="quality-empty"><strong>终审没有留下待处理问题</strong><p>仍可展开本地扫描，查看措辞和节奏方面的可选优化。</p></div>';
  return issues.slice(0,5).map(item=>`<details class="quality-issue-row"><summary><span><b>${escapeHtml(qualitySeverity(item.severity))}</b><strong>${escapeHtml(item.title||"正文问题")}</strong></span><small>${escapeHtml(qualityIssueStatus(item.status))}</small></summary><div><p><strong>为什么影响阅读</strong>${escapeHtml(item.effect||"可能影响理解、可信度或继续阅读的意愿。")}</p><p><strong>建议怎么改</strong>${escapeHtml(item.repair_direction||"结合上下文复核并修改。")}</p>${(item.evidence||[]).map(evidence=>`<blockquote><span>${escapeHtml(evidence.location||"正文相关位置")}</span>${escapeHtml(evidence.excerpt||"没有保留原文证据")}</blockquote>`).join("")}</div></details>`).join("");
}
function qualityCriteriaMarkup(score) {
  const entries=Object.entries(score.criteria||{});
  if(!entries.length)return '<p class="skill-meta">这份稿件还没有生成逐项评分，下一次全文终审会补齐。</p>';
  return entries.map(([key,value])=>{const evidence=(score.criterion_evidence||{})[key]||{};return `<details class="quality-criterion-row"><summary><span>${escapeHtml((score.criterion_labels||{})[key]||"评分项目")}</span><strong>${qualityScore(value)}</strong></summary><p><b>判断位置</b>${escapeHtml(evidence.location||"未记录")}</p><p><b>原文依据</b>${escapeHtml(evidence.excerpt||"未记录")}</p><p><b>为什么这样评分</b>${escapeHtml(evidence.effect||"未记录")}</p></details>`;}).join("");
}
function qualityReferencesMarkup(controls) {
  const active=controls.group?.items||[];
  const recommendations=controls.recommendations?.recommendations||[];
  const missingRoles=controls.recommendations?.missing_roles||[];
  const history=controls.history?.versions||[];
  const rows=recommendations.map(item=>`<label class="quality-reference-option"><input type="checkbox" data-quality-reference-id="${escapeHtml(item.id)}" ${item.status==="confirmed"?"checked":""}><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.role_label||"评分参考")} · ${escapeHtml(item.reason||"等待你确认")}</small></span></label>`).join("");
  const activeRows=active.map(item=>`<div class="quality-reference-active"><span><strong>${escapeHtml(item.title)}</strong><small>${escapeHtml(item.role_label||"评分参考")}</small></span><button class="secondary danger-text" type="button" data-quality-reference-remove="${escapeHtml(item.id)}">移出参考组</button></div>`).join("");
  const gaps=missingRoles.length?`<p class="quality-reference-gaps">当前可推荐资料还缺：${missingRoles.map(item=>escapeHtml(item.label)).join("、")}。这不影响终审，可后续补充。</p>`:"";
  return `<div class="quality-reference-intro"><strong>系统只会推荐，确认后才用于人工评分校准</strong><p>确认过程不会调用模型，也不会把参考作品全文发送给日常终审。</p></div>${gaps}<div class="quality-reference-list">${rows||'<p class="skill-meta">暂时没有可推荐的已确认资料。你仍可使用本项目历史最佳稿。</p>'}</div>${rows?'<button class="primary" type="button" data-quality-reference-confirm>确认所选参考</button>':""}${activeRows?`<section class="quality-active-references"><h4>当前已确认</h4>${activeRows}</section>`:""}${history.length?`<details class="quality-reference-history"><summary>查看确认和移除记录（${history.length}）</summary>${history.map(item=>`<p>版本 ${item.version} · ${item.action==="removed"?"移除参考":"确认参考"} · ${formatLocalTimestamp(item.created_at,true)}</p>`).join("")}</details>`:""}${controls.hasError?'<p class="error-text">部分参考组信息读取失败，刷新页面后可以重试。</p>':""}`;
}
function passageProtectionsMarkup(controls) {
  const items=controls.protections?.items||[];
  const rows=items.map(item=>`<div class="quality-protection-row ${item.active?"active":"inactive"}"><span><strong>${escapeHtml(item.label)}</strong><small>${escapeHtml(item.mode_label)} · ${escapeHtml(item.status_label)}</small></span><div>${item.active?`<button class="secondary" type="button" data-protection-allow="${escapeHtml(item.id)}">下次修改可变动一次</button>`:""}${item.active?`<button class="secondary danger-text" type="button" data-protection-remove="${escapeHtml(item.id)}">取消保护</button>`:""}</div></div>`).join("");
  return `<div class="quality-protection-controls"><label>保护名称<input id="candidate-protection-label" maxlength="80" placeholder="例如：喜欢的开头"></label><fieldset class="segmented"><legend>保护强度</legend><label><input type="radio" name="candidate-protection-mode" value="soft" checked><span>尽量不改文字</span></label><label><input type="radio" name="candidate-protection-mode" value="exact"><span>一个字也不改</span></label></fieldset><button class="secondary" type="button" data-protect-selection>保护选中的完整段落</button></div><div class="quality-protection-list">${rows||'<p class="skill-meta">还没有保护片段。在下方正文中选择完整段落后即可添加。</p>'}</div>`;
}
function renderCandidateQualityWorkspace(result,controls) {
  const shell=$("#candidate-quality"),summary=result.quality_summary||{},score=summary.score||{},word=summary.word_count||{};
  const authority=summary.publication_authority||{can_set_formal:false,blocking_reasons:["等待质量检查"]};
  const stateLabel=summary.manuscript_state?.protected_best?"受保护最佳稿":"候选稿";
  const dimensions=score.dimensions||{};
  const issues=summary.issues||[];
  const report=result.diagnostics||{findings:[]};
  const originality=result.analysis?.originality||{},nlp=result.analysis?.nlp||{},ledger=result.analysis?.narrative_ledger||{};
  const unresolved=[...(ledger.promises||[]),...(ledger.questions||[]),...(ledger.setups||[])].filter(item=>item.status==="unresolved");
  const wordMaximum=Number(word.maximum||1),wordPercent=Math.max(0,Math.min(100,Math.round(Number(word.current||0)/wordMaximum*100)));
  const localFindings=(report.findings||[]).slice(0,8).map(item=>`<p><strong>${escapeHtml(findingLabel(item.code))}</strong><span>第 ${item.segment} 段 · ${escapeHtml(item.excerpt)}</span></p>`).join("");
  shell.innerHTML=`<div class="candidate-quality-workspace"><header class="quality-workspace-head"><div><span class="quality-state ${summary.manuscript_state?.protected_best?"protected":""}">${stateLabel}</span><h3>${escapeHtml(summary.profile?.label||"稿件质量")}</h3><p class="quality-judge">终审模型：${escapeHtml(summary.profile?.judge_label||"旧记录未保存模型名称")}</p><p>${escapeHtml(score.comparison_message||"等待建立可比较的评分记录")}</p></div><div class="quality-next-action"><span>下一步</span><strong>${escapeHtml(summary.next_action||"继续检查候选稿")}</strong></div></header><div class="quality-score-strip"><div><span>总分</span><strong>${qualityScore(score.current)}</strong></div><div><span>阅读吸引力</span><strong>${qualityScore(dimensions.commercial)}</strong></div><div><span>故事质量</span><strong>${qualityScore(dimensions.story)}</strong></div><div><span>文字表达</span><strong>${qualityScore(dimensions.prose)}</strong></div></div><section class="quality-word-count"><div><strong>正文有效字数 ${Number(word.current||result.han_characters||0).toLocaleString()} 字</strong><span>目标 ${Number(word.minimum||0).toLocaleString()}～${Number(word.maximum||0).toLocaleString()} 个有效正文汉字</span></div><div class="quality-word-track" aria-label="正文篇幅进度"><span style="width:${wordPercent}%"></span></div></section>${authority.can_set_formal?'<div class="quality-ready"><strong>当前稿件已具备设为正式稿的条件</strong><span>按钮已启用，确认后才会替换原正式稿。</span></div>':`<details class="quality-blockers" open><summary>为什么现在不能设为正式稿</summary>${(authority.blocking_reasons||[]).map(reason=>`<p>${escapeHtml(reason)}</p>`).join("")}</details>`}<section class="quality-priority"><header><h3>最需要处理的问题</h3><span>${issues.length?`共 ${issues.length} 项，先显示最重要的 ${Math.min(5,issues.length)} 项`:"没有待处理终审问题"}</span></header>${qualityIssuesMarkup(issues)}</section><details class="quality-drawer"><summary><span><strong>查看本地扫描</strong><small>全文规则、原创候选和叙事账本</small></span><b>展开</b></summary><div class="quality-drawer-body"><div class="quality-local-summary"><span>自然度 <b>${Number(report.naturalness_score||0)}</b></span><span>阻断问题 <b>${Number(report.blocking_count||0)}</b></span><span>局部优化 <b>${Number(report.targeted_count||0)}</b></span><span>语义分析 <b>${nlp.available?"已完成":"标准规则"}</b></span></div>${localFindings?`<div class="candidate-findings">${localFindings}</div>`:'<p class="skill-meta">本地扫描未发现明显模板化问题。</p>'}<p class="skill-meta">原创检查只比较本地资料库：连续片段 ${Number(originality.continuous_passages?.length||0)} 处 · 人名 ${Number(originality.similar_names?.length||0)} 处 · 语义候选 ${Number(originality.semantic_candidates?.length||0)} 处</p><div class="quality-ledger-summary"><strong>叙事账本</strong><span>未兑现 ${unresolved.length} · 已关联 ${(ledger.relations||[]).length} · 场景 ${(ledger.scenes||[]).length}</span>${unresolved.slice(0,8).map(item=>`<p>${escapeHtml(item.kind||"线索")}：${escapeHtml(item.text||"")}</p>`).join("")}</div></div></details><details class="quality-drawer"><summary><span><strong>查看详细评分</strong><small>逐项分数、判断位置和原文依据</small></span><b>展开</b></summary><div class="quality-drawer-body quality-criteria-list">${qualityCriteriaMarkup(score)}</div></details><details class="quality-drawer"><summary><span><strong>评分参考组</strong><small>${(controls.group?.items||[]).length} 份已确认参考</small></span><b>展开</b></summary><div class="quality-drawer-body">${qualityReferencesMarkup(controls)}</div></details><details class="quality-drawer"><summary><span><strong>查看完整正文与保护片段</strong><small>${(controls.protections?.items||[]).filter(item=>item.active).length} 段保护中</small></span><b>展开</b></summary><div class="quality-drawer-body">${passageProtectionsMarkup(controls)}<pre id="candidate-manuscript-preview" class="quality-manuscript-preview" tabindex="0">${escapeHtml(result.content||"")}</pre></div></details></div>`;
  bindCandidateQualityActions(result.project_id);
  return authority;
}
function bindCandidateQualityActions(projectId) {
  $("#candidate-quality").querySelector("[data-quality-reference-confirm]")?.addEventListener("click",()=>confirmQualityReferences(projectId));
  $("#candidate-quality").querySelectorAll("[data-quality-reference-remove]").forEach(button=>button.addEventListener("click",()=>removeQualityReference(projectId,button.dataset.qualityReferenceRemove)));
  $("#candidate-quality").querySelector("[data-protect-selection]")?.addEventListener("click",()=>protectSelectedCandidatePassage(projectId));
  $("#candidate-quality").querySelectorAll("[data-protection-allow]").forEach(button=>button.addEventListener("click",()=>changePassageProtection(projectId,button.dataset.protectionAllow,"allow")));
  $("#candidate-quality").querySelectorAll("[data-protection-remove]").forEach(button=>button.addEventListener("click",()=>changePassageProtection(projectId,button.dataset.protectionRemove,"remove")));
}
async function reloadCandidateQuality(projectId,message) {
  setCandidateOperationStatus("busy",message,"正在更新页面状态");
  await loadCandidateQuality(projectId);
  if(state.candidateQuality)setCandidateOperationStatus("success",message,"页面已更新");
}
async function confirmQualityReferences(projectId) {
  const boxes=[...$("#candidate-quality").querySelectorAll("[data-quality-reference-id]")];
  const accepted_ids=boxes.filter(item=>item.checked).map(item=>item.dataset.qualityReferenceId);
  const rejected_ids=boxes.filter(item=>!item.checked).map(item=>item.dataset.qualityReferenceId);
  try{setCandidateOperationStatus("busy","正在保存评分参考组","不会调用模型，也不会删除原资料");await api(`/api/projects/${projectId}/quality-references/confirm`,{method:"POST",body:JSON.stringify({accepted_ids,rejected_ids})});await reloadCandidateQuality(projectId,"评分参考组已保存");}
  catch(error){setCandidateOperationStatus("error","评分参考组保存失败",error.message);}
}
async function removeQualityReference(projectId,itemId) {
  if(!confirm("只把这份资料移出评分参考组，原资料和分析结果都会保留。继续？"))return;
  try{setCandidateOperationStatus("busy","正在移出评分参考","原资料不会删除");await api(`/api/projects/${projectId}/quality-references/${encodeURIComponent(itemId)}`,{method:"DELETE"});await reloadCandidateQuality(projectId,"已移出评分参考组");}
  catch(error){setCandidateOperationStatus("error","移出失败",error.message);}
}
async function protectSelectedCandidatePassage(projectId) {
  const preview=$("#candidate-manuscript-preview"),selection=window.getSelection();
  const node=selection?.rangeCount?selection.getRangeAt(0).commonAncestorContainer:null;
  const element=node?.nodeType===3?node.parentElement:node;
  const excerpt=selection&&element&&preview.contains(element)?selection.toString().trim():"";
  if(!excerpt)return setCandidateOperationStatus("error","没有选中正文","请在下方正文中选择一个或多个完整段落");
  const mode=$("#candidate-quality").querySelector('input[name="candidate-protection-mode"]:checked')?.value||"soft";
  const label=$("#candidate-protection-label").value.trim()||"保护片段";
  try{setCandidateOperationStatus("busy","正在保存保护片段","只保存在当前作品中，不会调用模型");await api(`/api/projects/${projectId}/passage-protections`,{method:"POST",body:JSON.stringify({excerpt,mode,label})});selection.removeAllRanges();await reloadCandidateQuality(projectId,"保护片段已保存");}
  catch(error){setCandidateOperationStatus("error","没有保存保护片段",error.message);}
}
async function changePassageProtection(projectId,protectionId,action) {
  if(action==="remove"&&!confirm("取消后，后续返修可以修改这段文字。继续？"))return;
  const path=`/api/projects/${projectId}/passage-protections/${protectionId}${action==="allow"?"/allow-next-change":""}`;
  try{setCandidateOperationStatus("busy",action==="allow"?"正在允许下次修改一次":"正在取消保护","正文现在不会改变");await api(path,{method:action==="allow"?"POST":"DELETE"});await reloadCandidateQuality(projectId,action==="allow"?"下次返修可修改这段一次":"已取消保护");}
  catch(error){setCandidateOperationStatus("error","操作失败",error.message);}
}
async function loadCandidateQuality(projectId) {
  const shell=$("#candidate-quality"),publish=$("#publish-candidate");
  publish.hidden=true;publish.disabled=true;publish.title="";
  state.candidateQuality=null;state.candidateControls=null;
  if(!projectId){shell.innerHTML='<p class="skill-meta">请先选择作品</p>';setCandidateOperationStatus("","请先选择作品");return;}
  shell.innerHTML='<p class="skill-meta">正在读取候选稿、本地扫描和终审结果…</p>';
  setCandidateOperationStatus("busy","正在读取稿件质量","完成后会显示下一步");
  try{
    const result=await api(`/api/projects/${projectId}/candidate`);
    if(state.activeProject?.id!==projectId)return;
    if(!result.available){shell.innerHTML='<p class="skill-meta">尚无候选稿。完成正文生成后，这里会显示质量结论和下一步。</p>';setCandidateOperationStatus("","尚无候选稿","先生成或恢复一份正文候选稿");return;}
    const controls=await loadCandidateQualityControls(projectId);
    if(state.activeProject?.id!==projectId)return;
    state.candidateQuality=result;state.candidateControls=controls;
    const authority=renderCandidateQualityWorkspace(result,controls);
    const reasons=authority.blocking_reasons||[];
    publish.hidden=state.activeProject?.mode!=="short";
    publish.disabled=!authority.can_set_formal;
    publish.title=authority.can_set_formal?"确认后设为正式稿":reasons.join("；");
    setCandidateOperationStatus(authority.can_set_formal?"success":"warning",result.quality_summary?.next_action||"继续检查候选稿",authority.can_set_formal?"当前稿件已通过全部发布检查":reasons[0]||"等待质量检查");
  }catch(error){shell.innerHTML=`<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`;setCandidateOperationStatus("error","稿件质量读取失败",error.message);}
}
async function loadWritingRulesSummary(projectId) {
  const shell = $("#writing-rules-summary");
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/learning/effective-rules`);
    if (state.activeProject?.id !== projectId) return;
    state.effectiveRules=result;shell.innerHTML=effectiveRulesMarkup(result,true);
  } catch(error) { shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`; }
}
async function loadPublicationPanel(projectId){
  const panel=$("#platform-profile-panel"),form=$("#zhihu-publication-form"),status=$("#publication-status"),submit=form.querySelector('button[type="submit"]');state.publicationPreview=null;
  submit.disabled=true;submit.title="请先完成正式稿和终审检查";
  if(!projectId){panel.innerHTML='<p class="skill-meta">请先选择作品</p>';form.hidden=true;return;}
  const project=state.projects.find(item=>item.id===projectId);
  if(project?.mode!=="short"){panel.innerHTML='<p class="skill-meta">知乎盐选短篇创作配置只用于短篇作品，长篇保持原有流程。</p>';form.hidden=true;return;}
  const enabled=project.platform_profile_id==="zhihu-salt-short";
  panel.innerHTML=`<div class="profile-row"><div><strong>${enabled?"已启用知乎盐选短篇创作配置":"尚未指定发布平台"}</strong><p>${enabled?"后续大纲、正文、返修和终审会区分平台要求与市场建议。":"启用后只调整后续创作检查和投稿设置，不会改动现有正文。"}</p></div><button type="button" class="${enabled?"secondary":"primary"}" data-profile-toggle>${enabled?"停用配置":"启用知乎盐选短篇"}</button></div>`;
  panel.querySelector("[data-profile-toggle]").addEventListener("click",()=>changePlatformProfile(enabled?null:"zhihu-salt-short"));form.hidden=!enabled;if(!enabled)return;
  form.elements.title.value ||= project.title||"";form.elements.content_type.value ||= project.genre||"";
  status.className="operation-status busy";status.textContent="正在检查正式稿和终审结果…";
  try{state.publicationPreview=await api(`/api/projects/${projectId}/publication/zhihu/preview`);const ready=Boolean(state.publicationPreview.ready);submit.disabled=!ready;submit.title=ready?"生成新的投稿包，旧版本继续保留":`当前还不能生成投稿包：${state.publicationPreview.message}`;status.className=`operation-status ${ready?"success":"warning"}`;status.textContent=`${state.publicationPreview.message} 正文 ${Number(state.publicationPreview.character_count).toLocaleString()} 字。`;}
  catch(error){submit.disabled=true;submit.title="当前还不能生成投稿包";status.className="operation-status error";status.textContent=`投稿条件检查失败：${error.message}`;}
}
async function changePlatformProfile(profileId){
  if(!state.activeProject)return;
  try{const preview=await api(`/api/projects/${state.activeProject.id}/platform-profile/preview`,{method:"POST",body:JSON.stringify({profile_id:profileId})});if(!confirm(`${preview.message}\n\n${profileId?"确认启用知乎盐选短篇创作配置？":"确认停用平台创作配置？"}`))return;const changed=await api(`/api/projects/${state.activeProject.id}/platform-profile`,{method:"PUT",body:JSON.stringify({profile_id:profileId})});state.projects=state.projects.map(item=>item.id===changed.id?changed:item);state.activeProject=changed;await loadPublicationPanel(changed.id);toast(profileId?"知乎盐选短篇创作配置已启用":"平台创作配置已停用，正文没有改变");}
  catch(error){toast(error.message);}
}
$("#zhihu-publication-form")?.addEventListener("submit",async event=>{
  event.preventDefault();if(!state.activeProject)return;const form=event.target,button=form.querySelector('button[type="submit"]'),status=$("#publication-status");if(!state.publicationPreview?.ready){status.className="operation-status warning";status.textContent=`当前还不能生成投稿包：${state.publicationPreview?.message||"请先完成正式稿和终审检查"}`;return;}
  button.disabled=true;button.textContent="正在生成…";status.className="operation-status busy";status.textContent="正在整理投稿文件，不会调用模型或修改正文。";
  try{const data=Object.fromEntries(new FormData(form));const result=await api(`/api/projects/${state.activeProject.id}/publication/zhihu`,{method:"POST",body:JSON.stringify({...data,alternate_titles:String(data.alternate_titles||"").split(/\r?\n/).map(item=>item.trim()).filter(Boolean),expected_manuscript_hash:state.publicationPreview.manuscript_hash})});status.className="operation-status success";status.textContent=`${result.message} 文件位置：${result.path}`;toast(`投稿包 ${result.version} 已生成`);await loadProjectLocations(state.activeProject.id);}
  catch(error){status.className="operation-status error";status.textContent=`生成失败：${error.message}。已填写内容不会清空，可以直接重试。`;}
  finally{button.disabled=!state.publicationPreview?.ready;button.textContent="生成知乎投稿包";}
});
$("#open-learning-library").addEventListener("click", async () => {
  showView("learning", "学习库");
  if (state.activeProject) { $("#learning-project").value = state.activeProject.id; state.projectLearning = null; await loadProjectLearning(); renderLearning(); }
});
function renderStoryStateSection() {
  const section=$("#story-state-section").value; const value=state.storyState?.data?.[section];
  $("#story-state-value").value=value === undefined ? "" : JSON.stringify(value,null,2);
  $("#story-state-value").disabled=!state.storyState; $("#story-state-save").disabled=!state.storyState;
  $("#story-state-diff").hidden=true;
}
async function loadStoryState(projectId) {
  if (!projectId) {
    state.storyState=null; $("#story-state-revision").textContent="请先选择作品";
    $("#story-state-value").value=""; $("#story-state-value").disabled=true; $("#story-state-save").disabled=true; return;
  }
  try {
    const result=await api(`/api/projects/${projectId}/story-state`); if (state.activeProject?.id !== projectId) return;
    state.storyState=result; $("#story-state-revision").textContent=`版本 ${result.revision} · 正常写作时自动更新，人工纠错会保存新版本`;
    renderStoryStateSection();
  } catch(error) { state.storyState=null; $("#story-state-revision").textContent=error.message; renderStoryStateSection(); }
}
const materialSectionLabels = {
  "Appearance":"外貌", "Personality & Traits":"性格与特质", "Backstory":"背景经历",
  "Motivations & Goals":"动机与目标", "Voice & Speech Patterns":"语言与对白习惯",
  "Character Arc":"人物弧线", "Timeline":"人物时间线"
};
function materialImpact(groupId) {
  return ({characters:"后续生成、润色与人物一致性审核",world:"后续规划、生成与世界规则审核",locations:"后续场景生成与地点一致性审核",plot:"后续规划与结构审核",timeline:"后续生成与时间线审核",issues:"后续审核与定向修订",constraints:"全部后续生成和发布检查"})[groupId] || "后续写作";
}
function renderCharacter(profile, document) {
  const shell=$("#character-detail");
  if (!profile) { shell.innerHTML='<p class="skill-meta">暂无人物档案</p>'; return; }
  shell.innerHTML=`<header><div><p class="eyebrow">${escapeHtml(profile.role || "character")}</p><h2>${escapeHtml(profile.name)}</h2></div><div class="character-facts"><span>${escapeHtml(profile.age || "-")} 岁</span><span>${escapeHtml(profile.status || "-")}</span></div></header><div class="material-actions"><button class="secondary" data-material-edit>编辑人物档案</button></div><div class="character-tags">${(profile.tags || []).map(tag=>`<span>${escapeHtml(tag)}</span>`).join("")}</div>${profile.arc ? `<section><h3>人物弧线摘要</h3><p>${escapeHtml(profile.arc)}</p></section>` : ""}${(profile.sections || []).map(section=>`<section><h3>${escapeHtml(materialSectionLabels[section.title] || section.title)}</h3><div class="profile-copy">${escapeHtml(section.content)}</div></section>`).join("")}`;
  shell.querySelector("[data-material-edit]")?.addEventListener("click",()=>renderMaterialEditor(document,"characters"));
}
function renderMaterialDocument(document, groupId) {
  const shell=$("#character-detail");
  if (!document) { shell.innerHTML='<p class="skill-meta">此分区暂无资料文件</p>'; return; }
  const group=(state.materials?.groups || []).find(item=>item.id===groupId);
  const display=document.display || {title:document.title,metadata:[],sections:[{title:"内容",blocks:[{kind:"text",content:document.content}]}]};
  const blockHtml=block=>block.kind==="table" ? `<div class="material-table-wrap"><table class="material-table"><thead><tr>${(block.columns || []).map(value=>`<th>${escapeHtml(value)}</th>`).join("")}</tr></thead><tbody>${(block.rows || []).map(row=>`<tr>${row.map(value=>`<td>${escapeHtml(value)}</td>`).join("")}</tr>`).join("")}</tbody></table></div>` : `<div class="profile-copy">${escapeHtml(block.content || "")}</div>`;
  shell.innerHTML=`<header><div><p class="eyebrow">${escapeHtml(group?.label || groupId)}</p><h2>${escapeHtml(display.title)}</h2></div><div class="character-facts">${(display.metadata || []).map(item=>`<span>${escapeHtml(item.label)}：${escapeHtml(item.value)}</span>`).join("")}</div></header><div class="material-actions"><button class="secondary" data-material-edit>编辑资料</button></div>${(display.sections || []).map(section=>`<section><h3>${escapeHtml(section.title)}</h3>${(section.blocks || [section]).map(blockHtml).join("")}</section>`).join("") || '<p class="skill-meta">暂无可展示内容</p>'}`;
  shell.querySelector("[data-material-edit]").addEventListener("click",()=>renderMaterialEditor(document,groupId));
}
function renderMaterialEditor(document, groupId) {
  const shell=$("#character-detail");
  const linkOption=groupId==="characters" ? '<label class="material-link-option"><input type="checkbox" data-retire-settings checked><span>废弃被删除的设定，并检查关联项目资料</span></label>' : "";
  shell.innerHTML=`<header><div><p class="eyebrow">正在编辑</p><h2>${escapeHtml(document.title)}</h2></div></header><label class="material-editor">Markdown 内容<textarea rows="24" spellcheck="false">${escapeHtml(document.content)}</textarea></label>${linkOption}<p class="skill-meta">保存后影响：${escapeHtml(materialImpact(groupId))}。现有正文不会自动修改。</p><div class="material-actions"><button class="secondary" data-material-cancel>取消</button><button class="primary" data-material-save>保存资料</button></div>`;
  shell.querySelector("[data-material-cancel]").addEventListener("click",()=>renderSelectedMaterial());
  shell.querySelector("[data-material-save]").addEventListener("click",async()=>{
    const button=shell.querySelector("[data-material-save]"); button.disabled=true;
    try {
      const result=await api(`/api/projects/${state.activeProject.id}/materials/${document.path}`,{method:"PUT",body:JSON.stringify({content:shell.querySelector("textarea").value,expected_hash:document.hash,retire_removed_settings:Boolean(shell.querySelector("[data-retire-settings]")?.checked)})});
      toast(`资料已保存 · 项目状态版本 ${result.story_state_revision}`); await renderMaterials();
      if (result.material_impact) void analyzeMaterialImpact(result.material_impact.id);
    } catch(error) { toast(error.message); button.disabled=false; }
  });
}
function renderSelectedMaterial() {
  const group=(state.materials?.groups || []).find(item=>item.id===state.activeMaterialGroup);
  const documents=group?.documents || [];
  if (!documents.some(item=>item.path===state.activeMaterialPath)) state.activeMaterialPath=documents[0]?.path || null;
  $("#character-list").innerHTML=documents.map(item=>`<button class="character-list-item ${item.path===state.activeMaterialPath ? "active" : ""}" data-material-path="${escapeHtml(item.path)}"><strong>${escapeHtml(item.display?.title || item.title)}</strong><span>${escapeHtml(group?.label || "项目资料")}</span></button>`).join("") || '<p class="skill-meta">暂无资料文件</p>';
  $("#character-list").querySelectorAll("[data-material-path]").forEach(button=>button.addEventListener("click",()=>{state.activeMaterialPath=button.dataset.materialPath; renderSelectedMaterial();}));
  const document=documents.find(item=>item.path===state.activeMaterialPath);
  if (state.activeMaterialGroup==="characters") {
    const profile=(state.materials?.characters || []).find(item=>`characters/${item.file}`===state.activeMaterialPath);
    renderCharacter(profile,document);
  } else renderMaterialDocument(document,state.activeMaterialGroup);
}
async function renderMaterials() {
  const project=state.activeProject;
  if (!project) {
    state.materials=null; $("#materials-summary").innerHTML='<span>先创建一部作品。</span>';
    $("#character-list").innerHTML=""; renderCharacter(null); renderProjectLearningMaterials(null); await loadStoryState(null); return;
  }
  $("#materials-project").value=project.id;
  try {
    const [result,learning]=await Promise.all([api(`/api/projects/${project.id}/materials`),api(`/api/projects/${project.id}/learning`)]);
    if (state.activeProject?.id !== project.id) return;
    state.materials=result;
    $("#materials-summary").innerHTML=`<div class="metric"><strong>${escapeHtml(result.project.title)}</strong><span>作品</span></div><div class="metric"><strong>${result.project.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(result.project.target_words || 0).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${result.characters.length}</strong><span>人物档案</span></div>`;
    const groups=result.groups || [];
    if (!groups.some(item=>item.id===state.activeMaterialGroup)) state.activeMaterialGroup=groups[0]?.id || "characters";
    $("#material-tabs").innerHTML=groups.map(group=>`<button class="material-tab ${group.id===state.activeMaterialGroup ? "active" : ""}" data-material-group="${group.id}" role="tab">${escapeHtml(group.label)}<span>${group.documents.length}</span></button>`).join("");
    $("#material-tabs").querySelectorAll("[data-material-group]").forEach(button=>button.addEventListener("click",()=>{state.activeMaterialGroup=button.dataset.materialGroup; state.activeMaterialPath=null; renderMaterialsTabs();}));
    renderMaterialsTabs();
    renderMaterialImpacts(result.material_impacts || []);
    renderProjectLearningMaterials(learning);
    await loadStoryState(project.id);
  } catch(error) { $("#character-detail").innerHTML=`<p class="error-text">${escapeHtml(error.message)}</p>`; }
}
const learningArtifactLabels={creative_blueprint:"创作蓝图",short_causal_chain:"七步剧情结构",prose_baseline:"文笔规则",voice_profiles:"人物说话方式",epistemic_state:"人物认知状态",scene_briefs:"场景安排"};
const learningFieldLabels={status:"状态",mechanisms:"已采用的写法",rules:"执行规则",summary:"摘要",sentence_rhythm:"句子节奏",paragraph_rhythm:"段落节奏",dialogue:"对白规则",psychology:"心理描写",narrative_distance:"叙事距离",viewpoint:"视角",action_sensation:"动作与感官",professional_detail:"专业细节",forbidden_patterns:"避免使用",states:"认知记录",briefs:"场景",name:"名称",fact:"事实",interpretation:"作用",transfer_guidance:"使用方法",title:"标题",pov:"视角",entry_goal:"入场目标",obstacle:"阻碍",relationship_tension:"关系张力",required_state_change:"必要变化",information_boundary:"信息边界",reader_question:"读者问题",exit_state:"离场状态",locked_facts:"锁定事实",attraction_guidance:"剧情吸引力",causal_structure:"七步剧情结构",incidents:"触发事件",core_goal:"核心目标",inner_goal:"内在目标",surface_goal:"表面目标",cycles:"推进过程",effort:"人物努力",escalation:"阻碍升级",next_question:"下一个问题",result:"阶段结果",state_change:"状态变化",dynamics:"整体节奏",cycle_count:"推进轮数",target_cycle_range:"建议轮数",ending:"结局设计",opening:"开头设计",cost:"付出的代价",future_promise:"后续承诺",pressure:"现实压力",anomaly:"异常信号",question_chain:"问题链",reversal:"反转",ending_rule:"结尾规则",opening_rule:"开头规则",cycle_rules:"推进规则",question_rules:"问题规则",relationship_rules:"关系变化规则",reversal_rule:"反转规则",fit:"适配程度",finding:"发现",findings:"发现"};
const learningTechnicalFields=new Set(["provenance","key","id","node_id","source_id","review_state","valid","source","confidence","positions","occurrence_count"]);
function artifactSummary(item){const data=item.data||{};if(item.artifact_type==="creative_blueprint")return `${(data.mechanisms||[]).length} 条写法 · ${(data.rules||[]).length} 条规则`;if(item.artifact_type==="short_causal_chain")return "目标、推进与结局安排";if(item.artifact_type==="scene_briefs")return `${(data.briefs||[]).length} 个场景`;return `版本 ${item.version}`;}
function readableLearningValue(value,key="") {
  if (value===null || value===undefined || value==="") return '<span class="skill-meta">未设置</span>';
  if (Array.isArray(value)) return value.length ? `<ul>${value.map(item=>`<li>${typeof item==="object"?readableLearningValue(item):escapeHtml(item)}</li>`).join("")}</ul>` : '<span class="skill-meta">暂无</span>';
  if (typeof value==="object") {
    const entries=Object.entries(value).filter(([,item])=>item!==null&&item!==undefined&&item!==""&&(!Array.isArray(item)||item.length));
    const readable=entries.filter(([name])=>learningFieldLabels[name]&&!learningTechnicalFields.has(name));
    const technical=entries.filter(([name])=>!learningFieldLabels[name]||learningTechnicalFields.has(name));
    const main=readable.length?`<dl>${readable.map(([name,item])=>`<div><dt>${escapeHtml(learningFieldLabels[name])}</dt><dd>${readableLearningValue(item,name)}</dd></div>`).join("")}</dl>`:'<p class="skill-meta">暂无可展示内容</p>';
    const raw=technical.length?`<details class="learning-technical"><summary>技术详情</summary><dl>${technical.map(([name,item])=>`<div><dt>${escapeHtml(learningFieldLabels[name]||name)}</dt><dd>${readableLearningValue(item,name)}</dd></div>`).join("")}</dl></details>`:"";
    return main+raw;
  }
  if (key==="status") return escapeHtml({candidate:"候选",active:"生效中",stale:"待复核"}[value]||value);
  return `<span>${escapeHtml(value)}</span>`;
}
function renderProjectLearningMaterials(result) {
  const shell=$("#project-learning-materials"); if(!shell)return;
  if(!result){shell.innerHTML='<p class="skill-meta">请选择作品</p>';return;}
  const artifacts=result.artifacts||[], adoptions=result.adoptions||[];
  const sections=artifacts.map(item=>`<details class="project-learning-item"><summary><strong>${escapeHtml(learningArtifactLabels[item.artifact_type]||"学习资料")}</strong><span>${artifactSummary(item)} · ${item.status==="stale"?"待复核":"生效中"}</span></summary><div class="project-learning-copy">${readableLearningValue(item.data)}</div></details>`);
  if(adoptions.length) sections.splice(1,0,`<details class="project-learning-item"><summary><strong>已采用的写法</strong><span>${adoptions.length} 项</span></summary><div class="project-learning-copy">${readableLearningValue({mechanisms:adoptions.map(item=>item.data)})}</div></details>`);
  shell.innerHTML=sections.join("")||'<p class="skill-meta">尚未采纳学习机制或建立执行资料</p>';
}
function renderMaterialImpacts(impacts) {
  const shell=$("#material-impact-status");
  if (!impacts.length) { shell.hidden=true; shell.innerHTML=""; return; }
  const impact=impacts[0]; shell.hidden=false;
  const removed=(impact.removed_lines || []).slice(0,4).join("；");
  const proposals=impact.proposals || [];
  const statusText=({pending:"等待分析关联资料",analyzing:"正在分析关联资料",failed:"关联分析失败",no_impact:"没有发现需要联动的资料",ready:`发现 ${proposals.length} 项联动建议`})[impact.status] || impact.status;
  const analyzeButton=["pending","analyzing","failed"].includes(impact.status) ? '<button class="secondary" data-impact-analyze>分析关联资料</button>' : "";
  const applyButton=impact.status==="ready" ? '<button class="primary" data-impact-apply>应用所选修改</button>' : "";
  shell.innerHTML=`<div class="material-impact-head"><div><strong>${escapeHtml(statusText)}</strong><span class="skill-meta">${escapeHtml(impact.summary || (removed ? `已废弃：${removed}` : "人物设定已发生变化"))}</span></div><div class="material-impact-actions">${analyzeButton}${applyButton}<button class="secondary" data-impact-dismiss>忽略</button></div></div><div class="material-impact-proposals">${proposals.map(item=>`<label class="material-impact-proposal"><input type="checkbox" value="${escapeHtml(item.id)}" checked><span><strong>${escapeHtml(item.path)}</strong><p>${escapeHtml(item.reason || "保持项目资料与人物新设定一致")}</p><span class="material-impact-diff"><span>${escapeHtml(item.old_text)}</span><span>${escapeHtml(item.new_text)}</span></span></span></label>`).join("")}${impact.error ? `<p class="error-text">${escapeHtml(impact.error)}</p>` : ""}</div>`;
  shell.querySelector("[data-impact-analyze]")?.addEventListener("click",()=>analyzeMaterialImpact(impact.id));
  shell.querySelector("[data-impact-dismiss]")?.addEventListener("click",()=>dismissMaterialImpact(impact.id));
  shell.querySelector("[data-impact-apply]")?.addEventListener("click",()=>applyMaterialImpact(impact.id,[...shell.querySelectorAll('.material-impact-proposal input:checked')].map(item=>item.value)));
}
async function analyzeMaterialImpact(impactId) {
  if (!state.activeProject) return;
  const shell=$("#material-impact-status"); shell.hidden=false; shell.innerHTML='<div class="material-impact-head"><strong>正在使用项目资料更新模型分析关联内容...</strong></div>';
  try { await api(`/api/projects/${state.activeProject.id}/material-impacts/${impactId}/analyze`,{method:"POST"}); await renderMaterials(); }
  catch(error) { toast(error.message); await renderMaterials(); }
}
async function dismissMaterialImpact(impactId) {
  try { await api(`/api/projects/${state.activeProject.id}/material-impacts/${impactId}/dismiss`,{method:"POST"}); await renderMaterials(); }
  catch(error) { toast(error.message); }
}
async function applyMaterialImpact(impactId, proposalIds) {
  if (!proposalIds.length) return toast("请至少选择一项联动修改");
  try { const result=await api(`/api/projects/${state.activeProject.id}/material-impacts/${impactId}/apply`,{method:"POST",body:JSON.stringify({proposal_ids:proposalIds})}); toast(`关联资料已更新 · 项目状态版本 ${result.story_state_revision}`); await renderMaterials(); }
  catch(error) { toast(error.message); await renderMaterials(); }
}
function renderMaterialsTabs() {
  $("#material-tabs").querySelectorAll("[data-material-group]").forEach(item=>item.classList.toggle("active",item.dataset.materialGroup===state.activeMaterialGroup));
  renderSelectedMaterial();
}
function renderMaterialAudit(detail) {
  const shell=$("#material-audit-status"); shell.hidden=false;
  if (["queued","running","cancelling"].includes(detail.status)) { shell.className="material-audit-status busy"; shell.textContent="正在分窗检查项目资料与正文的一致性..."; return; }
  if (detail.status!=="completed") { shell.className="material-audit-status error"; shell.textContent=`冲突检查失败：${detail.error || "请查看工作台日志"}`; return; }
  const issues=detail.conflict_report?.issues || [];
  shell.className="material-audit-status";
  shell.innerHTML=`<div class="section-heading"><div><strong>发现 ${issues.length} 个前后文冲突</strong><p class="skill-meta">检查结果已写入动态问题台账，不会自动修改正文</p></div>${issues.length ? '<button class="primary" data-material-repair>按新设定修复正文</button>' : ""}</div>${issues.slice(0,8).map(item=>`<p><strong>${escapeHtml(item.severity || "-")}</strong><span>${escapeHtml(item.location || "位置未知")} · ${escapeHtml(item.evidence || item.action || "")}</span></p>`).join("")}`;
  shell.querySelector("[data-material-repair]")?.addEventListener("click",()=>run(`/api/projects/${state.activeProject.id}/runs/materials-repair`));
}
$("#material-check").addEventListener("click",()=>run(`/api/projects/${state.activeProject.id}/runs/materials-audit`));
$("#story-state-section").addEventListener("change", renderStoryStateSection);
$("#story-state-value").addEventListener("input", () => {
  if (!state.storyState) return;
  const section=$("#story-state-section").value; const before=JSON.stringify(state.storyState.data[section],null,2); const after=$("#story-state-value").value.trim();
  const diff=$("#story-state-diff"); diff.hidden=before === after; diff.textContent=before === after ? "" : `修改前\n${before}\n\n修改后\n${after}`;
});
$("#story-state-save").addEventListener("click", async () => {
  if (!state.activeProject || !state.storyState) return;
  let value; try { value=JSON.parse($("#story-state-value").value); } catch { return toast("项目状态内容格式不正确，请检查括号、引号和逗号"); }
  const section=$("#story-state-section").value;
  try {
    state.storyState=await api(`/api/projects/${state.activeProject.id}/story-state`,{method:"PUT",body:JSON.stringify({expected_revision:state.storyState.revision,section,value})});
    $("#story-state-revision").textContent=`版本 ${state.storyState.revision} · 已保存人工修改`;
    renderStoryStateSection(); toast("项目资料已保存为新版本");
  } catch(error) { toast(error.message); await loadStoryState(state.activeProject.id); }
});
$("#publish-candidate").addEventListener("click", async () => {
  if (!state.activeProject || !confirm("将当前最高分候选设为正式成品？原正式成品会被替换。")) return;
  const button=$("#publish-candidate");
  button.disabled=true;
  setCandidateOperationStatus("busy","正在设为正式稿","正在核对候选稿、终审结果和稿件版本");
  try {
    await api(`/api/projects/${state.activeProject.id}/candidate/publish`, {method:"POST"});
    await Promise.all([loadProjectLocations(state.activeProject.id), loadCandidateQuality(state.activeProject.id)]);
    setCandidateOperationStatus("success","正式稿已更新","原正式稿已被替换，当前候选稿和终审记录保持绑定");
  } catch(error) {
    const authority=state.candidateQuality?.quality_summary?.publication_authority;
    button.disabled=!authority?.can_set_formal;
    setCandidateOperationStatus("error","设为正式稿失败",error.message);
  }
});
async function renderActiveProject() {
  const p = state.activeProject;
  $("#short-actions").hidden = !p || p.mode !== "short"; $("#long-actions").hidden = !p || p.mode !== "long";
  $("#project-summary").innerHTML = p ? `<div class="metric"><strong>${escapeHtml(p.title)}</strong><span>当前作品</span></div><div class="metric"><strong>${p.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(p.target_words).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${escapeHtml(p.genre)}</strong><span>题材</span></div>` : '<span>先创建一部作品。</span>';
  $("#trash-project").disabled = !p;
  if (!p) { $("#run-list").innerHTML = ""; await loadProjectLocations(null); await loadCandidateQuality(null); await loadWritingRulesSummary(null); await loadPublicationPanel(null); await loadWorkflowAnalysis(); return; }
  await Promise.all([loadProjectLocations(p.id), loadCandidateQuality(p.id), loadWritingRulesSummary(p.id), loadPublicationPanel(p.id), loadWorkflowAnalysis()]);
  const runs = await api(`/api/projects/${p.id}/runs`);
  const initialization = runs.find(run => run.workflow === "initialize-skills");
  const initializing = initialization && ["queued","running","cancelling"].includes(initialization.status);
  const initialized = initialization?.status === "completed";
  const activeRun = runs.find(run => ["queued","running","cancelling"].includes(run.status));
  const latestRun = runs[0];
  $("#initialize-project").hidden = initialized || initializing;
  ["#run-short", "#run-setup", "#run-chapter"].forEach(selector => { $(selector).disabled = !initialized; });
  $("#run-list").innerHTML = runs.length ? runs.map(r => `<button class="run-row" data-run-detail="${r.id}"><div><strong>${escapeHtml(runLabel(r.workflow))}</strong><div class="skill-meta">${escapeHtml(runLabel(r.current_stage))} · ${escapeHtml(formatLocalTimestamp(r.created_at))}</div></div><span class="status ${isQualityRejected(r) ? "quality-rejected" : r.status}">${escapeHtml(runStatusLabel(r))}</span></button>`).join("") : '<p class="skill-meta">暂无运行记录</p>';
  document.querySelectorAll("[data-run-detail]").forEach(button => button.addEventListener("click", async () => showRunDetail(await api(`/api/runs/${button.dataset.runDetail}`))));
  if (!state.activeRun) {
    if (activeRun) monitorRun(activeRun);
    else if (latestRun) showRunDetail(await api(`/api/runs/${latestRun.id}`));
    else { $("#run-state").className="run-state error"; $("#run-state").textContent="作品尚未初始化，请点击“继续初始化”"; }
  }
}
$("#active-project").addEventListener("change", event => { state.activeProject = state.projects.find(p => p.id === event.target.value); state.activeCharacter=null; renderProjects(); });
$("#materials-project").addEventListener("change", async event => { state.activeProject = state.projects.find(p => p.id === event.target.value); state.activeCharacter=null; state.activeMaterialPath=null; $("#active-project").value=event.target.value; await renderMaterials(); });
$("#edit-project-learning").addEventListener("click", async () => {
  if(!state.activeProject)return toast("请先选择作品");
  showView("learning"); $("#learning-project").value=state.activeProject.id; state.projectLearning=null;
  await loadProjectLearning(); renderLearning();
});

function renderWizardDrafts() {
  const drafts = state.wizards.filter(item => item.status === "draft");
  $("#wizard-drafts").innerHTML = '<option value="">选择草稿</option>' + drafts.map(item => `<option value="${item.id}">${escapeHtml(item.answers?.title?.value || (item.mode === "long" ? "未命名长篇" : "未命名短篇"))}</option>`).join("");
  const learnedSourceIds=new Set(state.mechanisms.map(item=>item.source_id));
  $("#wizard-reference").innerHTML='<option value="">自己构思（原方式）</option>'+state.references.map(item=>`<option value="${item.id}">从《${escapeHtml(item.title)}》${learnedSourceIds.has(item.id)?"的学习成果":"开始学习并"}创建</option>`).join("");
}
function fieldControl(field, answer) {
  const value = answer?.value ?? field.default ?? "";
  if (field.type === "textarea") return `<textarea class="field-value" rows="4">${escapeHtml(value)}</textarea>`;
  if (field.id === "market_baseline_enabled") return `<select class="field-value"><option value="enabled" ${value!=="disabled"?"selected":""}>启用市场建议</option><option value="disabled" ${value==="disabled"?"selected":""}>不使用市场建议</option></select>`;
  if (field.id === "market_baseline_key") return `<select class="field-value"><option value="">暂不选择</option>${state.marketBaselines.map(item=>{const serialized=JSON.stringify(item.key);const label={insufficient:"样本不足",preliminary:"初步",advisory:"可用于建议"}[item.confidence_level];return `<option value="${escapeHtml(serialized)}" ${serialized===value?"selected":""}>${escapeHtml(platformLabel(item.key.platform))} · ${escapeHtml(item.key.category)} · ${escapeHtml(item.key.ranking_name)} · ${escapeHtml(lengthTypeLabel(item.key.length_type))}（${item.sample_count}篇，${label}）</option>`;}).join("")}</select>`;
  if (field.id === "platform_profile_id") return `<select class="field-value"><option value="none" ${value==="none"?"selected":""}>暂不指定发布平台</option><option value="zhihu-salt-short" ${value==="zhihu-salt-short"?"selected":""}>知乎盐选短篇</option></select>`;
  if (field.type === "select") return `<select class="field-value">${(field.options || []).map(option => `<option value="${escapeHtml(option)}" ${String(option) === String(value) ? "selected" : ""}>${escapeHtml(option)}</option>`).join("")}</select>`;
  if (field.type === "boolean") return `<input class="field-value" type="checkbox" ${value ? "checked" : ""}>`;
  const list = field.id === "genre" ? ' list="genre-options"' : field.id === "sub_genre" ? ' list="subgenre-options"' : "";
  return `<input class="field-value" type="${field.type === "number" ? "number" : "text"}" value="${escapeHtml(value)}"${list}>`;
}
function updateGenreOptions() {
  $("#genre-options").innerHTML = Object.keys(genres).map(value => `<option value="${escapeHtml(value)}"></option>`).join("");
  const genre = document.querySelector('[data-field="genre"] .field-value')?.value;
  const choices = genres[genre] || [...new Set(Object.values(genres).flat())];
  $("#subgenre-options").innerHTML = choices.map(value => `<option value="${escapeHtml(value)}"></option>`).join("");
}
function renderWizard() {
  const wizard = state.activeWizard; if (!wizard) return;
  $("#wizard-shell").hidden = false; $("#wizard-launcher").hidden = true;
  const steps = wizard.schema.steps; state.wizardStep = Math.max(0, Math.min(state.wizardStep, steps.length - 1));
  $("#wizard-steps").innerHTML = steps.map((step,index) => `<button class="wizard-step ${index === state.wizardStep ? "active" : ""}" data-wizard-step="${index}"><span>${index + 1}</span>${escapeHtml(step.title)}</button>`).join("");
  const step = steps[state.wizardStep]; $("#wizard-title").textContent = step.title;
  $("#wizard-source").textContent = step.skill_name ? `${step.skill_name} · ${step.skill_hash.slice(0,12)}` : "核心要求";
  $("#wizard-fields").innerHTML = step.fields.map(field => { const answer = wizard.answers[field.id] || {}; return `<div class="wizard-field" data-field="${escapeHtml(field.id)}" data-type="${field.type}"><label><span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>${fieldControl(field,answer)}</label>${field.lockable ? `<label class="policy-label">处理方式<select class="field-policy"><option value="locked" ${answer.policy === "locked" ? "selected" : ""}>严格锁定</option><option value="suggestible" ${!answer.policy || answer.policy === "suggestible" ? "selected" : ""}>可建议</option><option value="generated" ${answer.policy === "generated" ? "selected" : ""}>模型生成</option></select></label>` : ""}</div>`; }).join("");
  updateGenreOptions();
  document.querySelector('[data-field="genre"] .field-value')?.addEventListener("input", updateGenreOptions);
  updateMarketBaselineWizardState();
  document.querySelector('[data-field="market_baseline_enabled"] .field-value')?.addEventListener("change",updateMarketBaselineWizardState);
  document.querySelector('[data-field="platform"] .field-value')?.addEventListener("change",recommendMarketBaseline);
  document.querySelector('[data-field="genre"] .field-value')?.addEventListener("change",recommendMarketBaseline);
  $("#wizard-back").disabled = state.wizardStep === 0; $("#wizard-next").hidden = state.wizardStep === steps.length - 1; $("#wizard-analyze").hidden = state.wizardStep !== steps.length - 1; $("#wizard-confirm").hidden = state.wizardStep !== steps.length - 1;
  renderWizardConfirmedMethods(state.wizardStep === steps.length - 1);
  document.querySelectorAll("[data-wizard-step]").forEach(button => button.addEventListener("click", async () => { await saveWizardStep(); state.wizardStep = Number(button.dataset.wizardStep); renderWizard(); }));
  let timer; document.querySelectorAll(".field-value,.field-policy").forEach(control => control.addEventListener("input", () => { $("#wizard-save-state").textContent = "保存中"; clearTimeout(timer); timer=setTimeout(() => saveWizardStep().catch(error => toast(error.message)),500); }));
  renderWizardSummary();
  if (state.interviewWizardId === wizard.id) renderInterview(); else loadInterview().catch(error => toast(error.message));
}
async function loadWizardConfirmedMethods(){
  const wizard=state.activeWizard;if(!wizard)return;
  state.wizardMethodsFor=wizard.id;state.wizardConfirmedMethods=null;renderWizardConfirmedMethods(true);
  try{
    const methods=await api(`/api/wizards/${wizard.id}/confirmed-mechanisms`);
    if(state.activeWizard?.id!==wizard.id)return;
    state.wizardConfirmedMethods=methods;renderWizardConfirmedMethods(true);
  }catch(error){
    if(state.activeWizard?.id!==wizard.id)return;
    $("#wizard-confirmed-method-list").innerHTML=`<p class="error-text">读取失败：${escapeHtml(error.message)}</p>`;
  }
}
function renderWizardConfirmedMethods(show){
  const shell=$("#wizard-confirmed-methods"),list=$("#wizard-confirmed-method-list");if(!shell||!list)return;
  shell.hidden=!show;if(!show||!state.activeWizard)return;
  if(state.wizardMethodsFor!==state.activeWizard.id){loadWizardConfirmedMethods();return;}
  if(!state.wizardConfirmedMethods){list.innerHTML='<p class="skill-meta">正在读取已确认写法</p>';return;}
  list.innerHTML=state.wizardConfirmedMethods.length?state.wizardConfirmedMethods.map(item=>`<label class="wizard-method-item"><input type="checkbox" value="${item.id}" ${state.selectedWizardMethods.has(item.id)?"checked":""}><span><strong>${escapeHtml(item.name)}</strong><small>来自《${escapeHtml(item.source_title)}》</small><p>${escapeHtml(item.use)}</p></span></label>`).join(""):'<p class="skill-meta">学习库里还没有可直接带入的已确认写法。</p>';
  list.querySelectorAll("input").forEach(input=>input.addEventListener("change",()=>input.checked?state.selectedWizardMethods.add(input.value):state.selectedWizardMethods.delete(input.value)));
}
function updateMarketBaselineWizardState(){const enabled=document.querySelector('[data-field="market_baseline_enabled"] .field-value')?.value!=="disabled";const select=document.querySelector('[data-field="market_baseline_key"] .field-value');if(select)select.disabled=!enabled;}
function recommendMarketBaseline(){
  const select=document.querySelector('[data-field="market_baseline_key"] .field-value');if(!select||select.value)return;
  const platform=document.querySelector('[data-field="platform"] .field-value')?.value||"";
  const genre=document.querySelector('[data-field="genre"] .field-value')?.value||"";
  const length=state.activeWizard?.mode==="short"?"short":"long";
  const matches=state.marketBaselines.map((item,index)=>({item,index})).filter(({item})=>(!platform||platform.includes("知乎")?item.key.platform==="zhihu":item.key.platform===platform)&&(!genre||item.key.category===genre)&&item.key.length_type===length).sort((a,b)=>b.item.sample_count-a.item.sample_count);
  if(matches.length){select.value=JSON.stringify(matches[0].item.key);select.dispatchEvent(new Event("input",{bubbles:true}));}
}
function collectWizardStep() {
  const answers = {};
  document.querySelectorAll(".wizard-field").forEach(row => { const control=row.querySelector(".field-value"), type=row.dataset.type; let value=type === "boolean" ? control.checked : control.value; if (type === "number" && value !== "") value=Number(value); answers[row.dataset.field]={value,policy:row.querySelector(".field-policy")?.value || "suggestible"}; });
  return answers;
}
async function saveWizardStep() {
  if (!state.activeWizard) return; const answers=collectWizardStep(); const updated=await api(`/api/wizards/${state.activeWizard.id}/answers`,{method:"PUT",body:JSON.stringify({answers})}); state.activeWizard=updated; $("#wizard-save-state").textContent="已保存"; renderWizardSummary();
}
function renderWizardSummary() {
  const answers={...state.activeWizard.answers,...collectWizardStep()}; const locked=Object.entries(answers).filter(([,item]) => item.policy === "locked" && item.value !== ""); $("#wizard-summary").innerHTML=locked.length ? locked.map(([key,item]) => `<div class="summary-item"><strong>${escapeHtml(key)}</strong><span>${escapeHtml(item.value)}</span></div>`).join("") : '<span class="skill-meta">尚未锁定内容</span>';
}
async function loadInterview() {
  if (!state.activeWizard) return;
  const wizardId=state.activeWizard.id; state.interviewWizardId=wizardId;
  state.interviewMessages=await api(`/api/wizards/${wizardId}/interview`);
  if (state.activeWizard?.id === wizardId) { renderInterview(); if (state.interviewMessages.length) setInterviewStatus("访谈记录已恢复", "success"); }
}
function setInterviewStatus(message, kind="") { const box=$("#interview-status"); box.textContent=message; box.className=`interview-status ${kind}`; }
function renderInterview() {
  const wizard=state.activeWizard; if (!wizard) return;
  const labels={}; wizard.schema.steps.forEach(step => step.fields.forEach(field => labels[field.id]=field.label));
  const html=state.interviewMessages.map(message => {
    const suggestions=message.suggestion_status === "pending" ? (message.suggestions || []) : [];
    return `<div class="interview-message ${escapeHtml(message.role)}"><span class="interview-role">${message.role === "assistant" ? "AI 访谈编辑" : "你"}</span><div>${escapeHtml(message.content)}</div>${suggestions.length ? `<div class="interview-suggestions">${suggestions.map(item => `<label class="interview-suggestion"><input type="checkbox" data-interview-suggestion data-message-id="${message.id}" value="${escapeHtml(item.field_id)}" checked><span><strong>${escapeHtml(labels[item.field_id] || item.field_id)}：${escapeHtml(item.value)}</strong><small>${escapeHtml(item.reason || "可写回向导")}</small></span></label>`).join("")}</div>` : ""}</div>`;
  }).join("");
  $("#interview-messages").innerHTML=html || '<p class="skill-meta">点击“开始访谈”，AI 会结合当前表单提出第一个关键问题。</p>';
  $("#interview-messages").scrollTop=$("#interview-messages").scrollHeight;
  $("#interview-start").hidden=state.interviewMessages.length > 0;
  $("#interview-start").disabled=state.interviewBusy;
  $("#interview-send").disabled=state.interviewBusy;
  $("#interview-input").disabled=state.interviewBusy;
  $("#interview-apply").hidden=!document.querySelector("[data-interview-suggestion]");
  $("#interview-apply").disabled=state.interviewBusy;
}
async function sendInterview(message) {
  if (!state.activeWizard || state.interviewBusy) return;
  state.interviewBusy=true; renderInterview(); setInterviewStatus("正在保存表单并等待规划模型回复...", "busy");
  try {
    await saveWizardStep();
    await api(`/api/wizards/${state.activeWizard.id}/interview`,{method:"POST",body:JSON.stringify({message:message || null})});
    $("#interview-input").value=""; await loadInterview(); setInterviewStatus("AI 已回复，可以继续回答或应用建议", "success");
  } catch(error) { setInterviewStatus(`发送失败：${error.message}`, "error"); toast(error.message); }
  finally { state.interviewBusy=false; renderInterview(); }
}
async function applyInterviewSuggestions() {
  const selected=[...document.querySelectorAll("[data-interview-suggestion]:checked")];
  if (!selected.length) return toast("请选择要写回向导的建议");
  const grouped=new Map(); selected.forEach(input => { const list=grouped.get(input.dataset.messageId) || []; list.push(input.value); grouped.set(input.dataset.messageId,list); });
  state.interviewBusy=true; renderInterview(); setInterviewStatus("正在把所选建议写回向导...", "busy");
  try {
    for (const [messageId,fieldIds] of grouped) {
      const result=await api(`/api/wizards/${state.activeWizard.id}/interview/${messageId}/apply`,{method:"POST",body:JSON.stringify({field_ids:fieldIds})});
      state.activeWizard=result.wizard;
    }
    renderWizard(); await loadInterview(); setInterviewStatus("所选建议已写回向导", "success"); toast("所选建议已写回向导");
  } catch(error) { setInterviewStatus(`应用失败：${error.message}`, "error"); toast(error.message); }
  finally { state.interviewBusy=false; renderInterview(); }
}
$("#interview-start").addEventListener("click", () => sendInterview(null));
$("#interview-form").addEventListener("submit", event => { event.preventDefault(); const message=$("#interview-input").value.trim(); if (!message) return toast("请先输入你的想法"); sendInterview(message); });
$("#interview-apply").addEventListener("click", applyInterviewSuggestions);
async function startWizardFromReference() {
  const referenceId=this?.dataset?.referenceCreate!==undefined ? state.activeReference?.id : $("#wizard-reference").value;
  const mode=document.querySelector('input[name="wizard-mode"]:checked').value;
  try {
    if(referenceId&&!state.mechanisms.some(item=>item.source_id===referenceId)){
      toast("正在先提炼参考小说的写作机制...");
      await api(`/api/references/${referenceId}/learn`,{method:"POST"});
      state.mechanisms=await api("/api/learning/mechanisms");
      renderWizardDrafts(); renderLearning();
    }
    const confirmedFromSource=referenceId?state.mechanisms.filter(item=>item.source_id===referenceId&&item.status==="confirmed").map(item=>item.id):[];
    if(referenceId&&!confirmedFromSource.length){
      switchLearningView("mechanisms");showView("learning");
      toast("这份资料还没有已确认写法。请先在候选写法中保留需要的内容，再创建新作品。");
      return;
    }
    let wizard=await api("/api/wizards",{method:"POST",body:JSON.stringify({mode})});
    if(referenceId){
      const source=state.references.find(item=>item.id===referenceId);
      const mechanisms=state.mechanisms.filter(item=>item.source_id===referenceId).map(item=>item.data);
      const guidance=mechanisms.map(item=>`${item.name||"创作机制"}：${item.transfer_guidance||item.interpretation||item.fact||""}`).filter(Boolean).join("\n");
      const answers={premise:{value:`基于《${source?.title||"参考资料"}》提炼的可迁移机制进行原创构思：\n${guidance}`,policy:"suggestible"}};
      const fieldIds=new Set(wizard.schema.steps.flatMap(step=>step.fields.map(field=>field.id)));
      if(fieldIds.has("plot.main_arc")) answers["plot.main_arc"]={value:`待在此基础上补充原创人物、冲突、转折与结局。\n${guidance}`,policy:"suggestible"};
      wizard=await api(`/api/wizards/${wizard.id}/answers`,{method:"PUT",body:JSON.stringify({answers})});
    }
    state.activeWizard=wizard; state.wizardStep=0;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set(confirmedFromSource);state.wizardSourceReferenceId=referenceId||null;state.wizardAutoOutline=Boolean(referenceId&&$("#wizard-auto-outline")?.checked); state.wizards.unshift(wizard); showView("projects"); renderWizard();
    if(referenceId) toast(`已带入 ${confirmedFromSource.length} 条确认写法；只需补充新故事的基本信息`);
  } catch(error) { toast(error.message); }
}
$("#start-wizard").addEventListener("click", startWizardFromReference);
$("#wizard-drafts").addEventListener("change", async event => { if (!event.target.value) return; state.activeWizard=await api(`/api/wizards/${event.target.value}`); state.wizardStep=0;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set(); renderWizard(); });
$("#wizard-back").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep--; renderWizard(); });
$("#wizard-next").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep++; renderWizard(); });
$("#wizard-analyze").addEventListener("click", async () => { try { await saveWizardStep(); state.activeWizard=await api(`/api/wizards/${state.activeWizard.id}/analyze`,{method:"POST"}); state.wizardStep=state.activeWizard.schema.steps.length-1; renderWizard(); toast(state.activeWizard.status === "ready" ? "关键资料完整" : "已生成必要追问"); } catch(error) { toast(error.message); } });
$("#wizard-confirm").addEventListener("click", async () => {
  try {
    await saveWizardStep();
    const selected=[...state.selectedWizardMethods],autoOutline=state.wizardAutoOutline&&selected.length;
    const project=await api(`/api/wizards/${state.activeWizard.id}/confirm`,{method:"POST",body:JSON.stringify({selected_mechanism_ids:selected})});
    state.projects.unshift(project);state.activeProject=project;state.activeWizard=null;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set();state.wizardSourceReferenceId=null;state.wizardAutoOutline=false;$("#wizard-shell").hidden=true;$("#wizard-launcher").hidden=false;renderProjects();
    if(autoOutline){
      showView("learning");$("#learning-project").value=project.id;switchLearningView("application");setOutlineOperationStatus("busy","正在生成第一版候选大纲","规划模型正在把已确认写法整理成原创大纲，完成后由你决定是否采用。");
      try{await api(`/api/projects/${project.id}/learning/generate-outline`,{method:"POST",body:JSON.stringify({brief:"根据已确认写法和当前新故事设定，生成第一版原创候选大纲；不得复用来源作品的人物、设定、独特表达和具体情节。"})});await loadProjectLearning();setOutlineOperationStatus("success","第一版候选大纲已生成","打开全文查看，确认后才会成为正式大纲。");}catch(error){setOutlineOperationStatus("error","候选大纲生成失败",`${error.message}。作品已经创建，可以稍后重试。`);}
    }else showView("workbench");
    const initialized=await api(`/api/projects/${project.id}/initialize-skills`,{method:"POST"});monitorRun(initialized);
  } catch(error) { toast(error.message); }
});

async function run(path, body) {
  if (!state.activeProject) return toast("请先创建作品");
  const box = $("#run-state"); box.className = "run-state busy"; box.textContent = "飞轮运行中，请保持此页面打开...";
  try { const result = await api(path, {method:"POST", body:body ? JSON.stringify(body) : undefined}); monitorRun(result); }
  catch (error) { box.className = "run-state error"; box.textContent = error.message; }
}
function renderRunLog(events) {
  $("#run-log").innerHTML = events.length ? events.map(item => {
    const message = item.message || `${item.event_type || "event"}: 未返回可用诊断信息`;
    return `<div class="log-row ${escapeHtml(item.severity)}"><span class="log-time">${escapeHtml(formatLocalTimestamp(item.created_at, true))}</span><span class="log-stage">${escapeHtml(runLabel(item.stage || item.event_type))}</span><span>${escapeHtml(readableRunMessage(message))}</span></div>`;
  }).join("") : '<p class="skill-meta">等待第一条运行日志...</p>';
  $("#run-log").scrollTop = $("#run-log").scrollHeight;
}
function renderRunContext(detail) {
  const events=detail.events || []; const loaded=new Map();
  events.filter(item => item.event_type === "skills_loaded").forEach(item => loaded.set(item.stage,item.metadata || {}));
  const pendingFallbacks=new Set(); const completed=[];
  events.forEach(item => { if(item.event_type === "model_fallback") pendingFallbacks.add(item.stage); if(item.event_type === "stage_completed") { completed.push({...item,usedFallback:pendingFallbacks.has(item.stage)}); pendingFallbacks.delete(item.stage); } });
  const stages=completed.map(item => { const meta=item.metadata || {}; const context=loaded.get(item.stage) || {}; return `<div class="context-stage"><div><strong>${escapeHtml(runLabel(item.stage))}</strong><span>${escapeHtml(meta.model_name || "未记录模型")}${item.usedFallback ? " · 已回退" : ""}</span></div><dl><dt>写作能力</dt><dd>${escapeHtml((context.skills || meta.skills || []).join("、") || "无")}</dd><dt>提示词</dt><dd>${Number(context.prompt_characters || 0).toLocaleString()} 字符</dd><dt>约束</dt><dd>${Number(context.constraint_characters || 0).toLocaleString()} 字符</dd><dt>模型用量</dt><dd>${Number(meta.input_tokens || 0).toLocaleString()} 输入 · ${Number(meta.output_tokens || 0).toLocaleString()} 输出</dd><dt>执行</dt><dd>${escapeHtml(runLabel(meta.execution_mode || "普通请求"))}</dd></dl></div>`; });
  const tools=detail.tool_receipts || [];
  const audit=detail.quality_report?.final_review_evidence; const counts=audit?.reconciliation_counts || {};
  const quality=audit ? `<div class="context-tools"><strong>${audit.review_mode==="incremental"?"关联窗口复核":"全文终审"}</strong><span>覆盖 ${Math.round(Number(audit.coverage || 0)*100)}% · ${Number(audit.reviewed_windows || 0)}/${Number(audit.window_count || 0)} 窗口 · 节省约 ${Number(audit.estimated_saved_input_characters || 0).toLocaleString()} 输入字符${(audit.fallback_reasons || []).length ? ` · 全文回退：${escapeHtml(audit.fallback_reasons.join("、"))}` : ""} · 已解决 ${Number(counts.resolved || 0)} · 部分解决 ${Number(counts.partially_resolved || 0)} · 未解决 ${Number(counts.unresolved || 0)}${(audit.gate_reasons || []).length ? ` · 阻断：${escapeHtml(audit.gate_reasons.join("、"))}` : ""}</span></div>` : "";
  const issues=detail.quality_report?.review?.issues||detail.quality_report?.issues||[];
  const issueLedger=issues.length?`<details class="quality-ledger"><summary><span><strong>问题返修台账</strong><small>${issues.length} 项 · 未解决优先</small></span><span>展开</span></summary><div class="ledger-list">${[...issues].sort((a,b)=>(a.status==="resolved")-(b.status==="resolved")).map(item=>`<details><summary><span class="ledger-status ${item.status==="resolved"?"resolved":""}">${item.status==="resolved"?"已解决":"待处理"}</span>${escapeHtml(findingLabel(item.issue_id||item.category||"问题"))}</summary><p><strong>证据：</strong>${escapeHtml(item.evidence||"未提供")}</p><p><strong>修复目标：</strong>${escapeHtml(item.repair_goal||item.action||"待确认")}</p></details>`).join("")}</div></details>`:"";
  $("#run-context").innerHTML=(stages.join("") || '<p class="skill-meta">本次运行尚无已完成阶段</p>') + quality + issueLedger + (tools.length ? `<div class="context-tools"><strong>工具调用记录</strong><span>${tools.length} 条 · ${escapeHtml([...new Set(tools.map(item => runLabel(item.execution_mode)))].join("、"))}</span></div>` : "");
}
document.querySelectorAll("[data-run-tab]").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll("[data-run-tab]").forEach(item => item.classList.toggle("active",item === button));
  $("#run-log").hidden=button.dataset.runTab !== "log"; $("#run-context").hidden=button.dataset.runTab !== "context";
}));
function showRunDetail(detail) {
  renderRunLog(detail.events || []);
  renderRunContext(detail);
  const active=["queued","running","cancelling"].includes(detail.status);
  const initialization=detail.workflow === "initialize-skills";
  const qualityRejected=isQualityRejected(detail);
  $("#run-state").className=`run-state ${active ? "busy" : qualityRejected ? "warning" : detail.status === "failed" ? "error" : detail.status}`;
  $("#run-state").textContent=active ? `正在执行：${runLabel(detail.current_stage || detail.workflow)}` : detail.status === "completed" ? (initialization ? "初始化及校验已完成，可以开始写作" : "任务执行完成") : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : detail.status === "failed" ? `${initialization ? "初始化" : "任务"}失败：${readableRunMessage(detail.error || "请查看日志")}` : `${runStatusLabel(detail)}：${readableRunMessage(detail.error || "请查看日志")}`;
}
async function monitorRun(runRecord) {
  clearTimeout(state.pollTimer); state.activeRun=runRecord.id; $("#run-cancel").hidden=false;
  const poll = async () => {
    try {
      const detail=await api(`/api/runs/${state.activeRun}`); renderRunLog(detail.events || []); renderRunContext(detail);
      if (detail.workflow==="materials-audit") renderMaterialAudit(detail);
      const active=["queued","running","cancelling"].includes(detail.status); const qualityRejected=isQualityRejected(detail); $("#run-state").className=`run-state ${active ? "busy" : qualityRejected ? "warning" : detail.status === "failed" ? "error" : detail.status}`;
      $("#run-state").textContent=detail.status === "cancelling" ? "正在终止当前阶段..." : active ? `正在执行：${runLabel(detail.current_stage || detail.workflow)}` : detail.status === "completed" ? "执行完成" : detail.status === "cancelled" ? "本次任务已终止，作品仍可继续写作" : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : `${runStatusLabel(detail)}：${readableRunMessage(detail.error || "请查看日志")}`;
      if (active) state.pollTimer=setTimeout(poll,900); else { state.activeRun=null; $("#run-cancel").hidden=true; await renderActiveProject(); if (detail.status === "completed") toast("飞轮执行完成"); }
    } catch(error) { $("#run-state").className="run-state error"; $("#run-state").textContent=error.message; $("#run-cancel").hidden=true; }
  };
  await poll();
}
$("#run-cancel").addEventListener("click", async () => { if (!state.activeRun) return; try { await api(`/api/runs/${state.activeRun}/cancel`,{method:"POST"}); $("#run-state").textContent="正在终止当前阶段..."; } catch(error) { toast(error.message); } });
$("#initialize-project").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/initialize-skills`));
$("#run-short").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/short`));
$("#run-setup").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/setup`));
$("#run-chapter").addEventListener("click", () => { const chapter_goal = $("#chapter-goal").value.trim(); if (!chapter_goal) return toast("请填写本章目标"); run(`/api/projects/${state.activeProject.id}/runs/chapter`, {chapter_goal}); });
$("#open-manuscript").addEventListener("click", async () => {
  if (!state.activeProject) return;
  try {
    const result = await api(`/api/projects/${state.activeProject.id}/manuscript`);
    $("#manuscript").textContent = result.content || "尚未生成正文";
    const panel = $("#manuscript-panel");
    panel.hidden = false;
    panel.scrollIntoView({behavior:"smooth",block:"start"});
  } catch(error) { toast(error.message); }
});
$("#close-manuscript").addEventListener("click", () => $("#manuscript-panel").hidden = true);
$("#migrate-project").addEventListener("click", async () => { if (!state.activeProject) return toast("请先选择作品"); try { const preview=await api(`/api/projects/${state.activeProject.id}/migration`); if (!confirm(`将映射 ${preview.mapped_facts.length} 条设定，${preview.ambiguous_facts.length} 条需要复核。继续？`)) return; await api(`/api/projects/${state.activeProject.id}/migration`,{method:"POST"}); toast("项目迁移和校验完成"); } catch(error) { toast(error.message); } });
async function trashProject(projectId) {
  if (state.activeRun && state.activeProject?.id === projectId) return toast("请先终止正在运行的任务");
  if (!confirm("将这部作品移入回收站？正文、设定和运行记录都会保留。")) return;
  try { await api(`/api/projects/${projectId}`,{method:"DELETE"}); await loadAll(); toast("作品已移入回收站"); }
  catch(error) { toast(error.message); }
}
$("#trash-project").addEventListener("click", () => { if (state.activeProject) trashProject(state.activeProject.id); });
function renderTrash() {
  $("#trash-list").innerHTML = state.trash.length ? state.trash.map(item => `<div class="data-row"><div><strong>${escapeHtml(item.title)}</strong><div class="skill-meta">${escapeHtml(item.mode)} · 删除于 ${escapeHtml(formatLocalTimestamp(item.trashed_at))}</div></div><div class="project-actions"><button class="secondary" data-restore="${item.id}">恢复</button><button class="danger-button" data-permanent="${item.id}">永久删除</button></div></div>`).join("") : '<p class="skill-meta">回收站为空</p>';
  document.querySelectorAll("[data-restore]").forEach(button => button.addEventListener("click", async () => { try { await api(`/api/projects/${button.dataset.restore}/restore`,{method:"POST"}); await loadAll(); toast("作品已恢复"); } catch(error) { toast(error.message); } }));
  document.querySelectorAll("[data-permanent]").forEach(button => button.addEventListener("click", async () => { if (!confirm("永久删除后无法恢复，确定继续？")) return; try { await api(`/api/projects/${button.dataset.permanent}/permanent`,{method:"DELETE"}); await loadAll(); toast("作品已永久删除"); } catch(error) { toast(error.message); } }));
}

function resetProviderForm() {
  const form = $("#provider-form");
  state.editingProviderId = null;
  form.reset();
  form.elements.api_key.required = true;
  $("#provider-form-title").textContent = "添加供应商";
  $("#provider-submit").textContent = "保存供应商";
  $("#provider-cancel").hidden = true;
}
$("#provider-cancel").addEventListener("click", resetProviderForm);
$("#provider-form").addEventListener("submit", async event => {
  event.preventDefault();
  const data = Object.fromEntries(new FormData(event.target));
  const editing = state.editingProviderId;
  const current = editing ? state.providers.find(provider => provider.id === editing) : null;
  if (current) Object.assign(data, {auth_type:current.auth_type, timeout_seconds:current.timeout_seconds, extra_headers:current.extra_headers});
  try {
    await api(editing ? `/api/providers/${editing}` : "/api/providers", {method:editing ? "PUT" : "POST", body:JSON.stringify(data)});
    resetProviderForm();
    await loadAll();
    toast(editing ? "供应商已更新" : "供应商已保存，接口密钥已进入系统凭据库");
  } catch(error) { toast(error.message); }
});
$("#model-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); const provider = data.provider_id; delete data.provider_id; try { await api(`/api/providers/${provider}/models`, {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("模型映射已保存"); } catch(error) { toast(error.message); } });
function renderProviders() {
  $("#model-provider").innerHTML = state.providers.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  $("#provider-list").innerHTML = state.providers.length ? state.providers.map(p => `<div class="data-row"><div><strong>${escapeHtml(p.name)}</strong><div class="skill-meta">${escapeHtml(p.protocol)} · ${escapeHtml(p.base_url)}</div><div class="key-update"><input type="password" autocomplete="new-password" placeholder="${p.has_api_key ? "更新接口密钥" : "接口密钥缺失，请重新输入"}" data-key-input="${p.id}"><button class="secondary" data-key-save="${p.id}">保存密钥</button></div>${p.models.map(m => `<div class="model-row"><strong>${escapeHtml(m.display_name)}</strong><div class="model-actions"><button class="secondary" data-probe-provider="${p.id}" data-probe-model="${m.id}" ${p.has_api_key ? "" : "disabled"}>检测模型</button><span id="probe-${m.id}" class="probe-result">${p.has_api_key ? "尚未检测" : "请先更新密钥"}</span></div></div>`).join("")}</div><div class="provider-actions"><span class="badge ${p.has_api_key ? "" : "missing"}">${p.has_api_key ? `${p.models.length} 个模型` : "密钥缺失"}</span><button class="secondary" data-provider-edit="${p.id}">编辑</button><button class="danger-button" data-provider-delete="${p.id}">删除</button></div></div>`).join("") : '<p class="skill-meta">尚未配置供应商</p>';
  document.querySelectorAll("[data-provider-edit]").forEach(button => button.addEventListener("click", () => {
    const provider=state.providers.find(item => item.id === button.dataset.providerEdit); if (!provider) return;
    const form=$("#provider-form"); state.editingProviderId=provider.id;
    form.elements.name.value=provider.name; form.elements.protocol.value=provider.protocol; form.elements.base_url.value=provider.base_url;
    form.elements.api_key.value=""; form.elements.api_key.required=false;
    $("#provider-form-title").textContent="编辑供应商"; $("#provider-submit").textContent="保存修改"; $("#provider-cancel").hidden=false;
    form.scrollIntoView({behavior:"smooth",block:"start"}); form.elements.name.focus();
  }));
  document.querySelectorAll("[data-provider-delete]").forEach(button => button.addEventListener("click", async () => {
    const provider=state.providers.find(item => item.id === button.dataset.providerDelete); if (!provider) return;
    if (!confirm(`删除供应商“${provider.name}”？它下面的 ${provider.models.length} 个模型映射也会删除。`)) return;
    try { await api(`/api/providers/${provider.id}`,{method:"DELETE"}); if (state.editingProviderId === provider.id) resetProviderForm(); await loadAll(); toast("供应商已删除"); }
    catch(error) { toast(error.message); }
  }));
  document.querySelectorAll("[data-key-save]").forEach(button => button.addEventListener("click", async () => {
    const input=document.querySelector(`[data-key-input="${button.dataset.keySave}"]`); const apiKey=input.value.trim();
    if (!apiKey) return toast("请输入新的接口密钥"); button.disabled=true;
    try { await api(`/api/providers/${button.dataset.keySave}/api-key`,{method:"PUT",body:JSON.stringify({api_key:apiKey})}); input.value=""; await loadAll(); toast("接口密钥已更新，可以检测模型了"); }
    catch(error) { toast(error.message); } finally { button.disabled=false; }
  }));
  document.querySelectorAll("[data-probe-model]").forEach(button => button.addEventListener("click", async () => {
    const resultBox=$(`#probe-${button.dataset.probeModel}`); resultBox.className="probe-result"; resultBox.textContent="检测中..."; button.disabled=true;
    try { const result=await api(`/api/providers/${button.dataset.probeProvider}/models/${button.dataset.probeModel}/probe`,{method:"POST"}); const all=result.chat&&result.structured_output&&result.tool_calling; const partial=result.chat&&!all; resultBox.className=`probe-result ${all ? "success" : partial ? "partial" : "error"}`; resultBox.textContent=`连接 ${result.chat ? "✓" : "×"} · 结构化回复 ${result.structured_output ? "✓" : "×"} · 工具 ${result.tool_calling ? "✓" : "×"}${result.error ? ` · ${result.error}` : ""}`; }
    catch(error) { resultBox.className="probe-result error"; resultBox.textContent=error.message; } finally { button.disabled=false; }
  }));
}
function modelOptions() { return state.providers.flatMap(p => p.models.map(m => `<option value="${p.id}|${m.id}">${escapeHtml(p.name)} / ${escapeHtml(m.display_name)}</option>`)).join(""); }
function renderBindings() {
  const options = modelOptions();
  $("#role-bindings").innerHTML = Object.entries(roles).map(([role,label]) => `<div class="binding-row"><strong>${label}</strong><label class="binding-control"><span>主模型</span><select id="binding-primary-${role}"><option value="">请选择模型</option>${options}</select></label><label class="binding-control"><span>备用模型</span><select id="binding-fallback-${role}"><option value="">使用程序默认回退</option>${options}</select></label><button class="secondary" data-bind="${role}">保存</button></div>`).join("");
  document.querySelectorAll("[data-bind]").forEach(button => button.addEventListener("click", async () => {
    const role = button.dataset.bind;
    const primaryValue = $(`#binding-primary-${role}`).value;
    const fallbackValue = $(`#binding-fallback-${role}`).value;
    if (!primaryValue) return toast("请选择主模型");
    if (fallbackValue && fallbackValue === primaryValue) return toast("主模型和备用模型不能相同");
    const [primary_provider_id, primary_model_id] = primaryValue.split("|");
    const [fallback_provider_id, fallback_model_id] = fallbackValue ? fallbackValue.split("|") : [null, null];
    try {
      await api(`/api/role-bindings/${role}`, {method:"PUT", body:JSON.stringify({primary_provider_id,primary_model_id,fallback_provider_id,fallback_model_id})});
      toast("角色绑定已保存");
    } catch(error) { toast(error.message); }
  }));
  api("/api/role-bindings").then(bindings => bindings.forEach(binding => {
    const primary = $(`#binding-primary-${binding.role}`);
    const fallback = $(`#binding-fallback-${binding.role}`);
    if (primary) primary.value = `${binding.primary_provider_id}|${binding.primary_model_id}`;
    if (fallback && binding.fallback_provider_id && binding.fallback_model_id) fallback.value = `${binding.fallback_provider_id}|${binding.fallback_model_id}`;
  })).catch(error => toast(error.message));
}
function renderSkills() {
  $("#skill-list").innerHTML = state.skills.length ? state.skills.map(s => `<div class="data-row"><div><strong>${escapeHtml(s.name)}</strong><div class="skill-meta">${escapeHtml(s.path)}<br>${s.content_hash.slice(0,16)}</div>${s.conflicts?.length ? `<div class="skill-conflicts">${s.conflicts.map(item => `<p><strong>${escapeHtml(item.code)}</strong>${escapeHtml(item.message)}</p>`).join("")}</div>` : ""}</div><div>${s.executable ? '<span class="badge">执行型</span>' : s.has_scripts ? '<span class="badge">提示词 · 含辅助脚本</span>' : '<span class="badge">提示词</span>'} ${s.conflicts?.length ? `<span class="badge conflict">冲突 ${s.conflicts.length}</span>` : ""} ${s.approved ? '<span class="status">已启用</span>' : `<button class="secondary" data-approve="${escapeHtml(s.name)}" data-hash="${s.content_hash}">授权</button>`}</div></div>`).join("") : '<p class="skill-meta">未发现写作能力</p>';
  document.querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", async () => { try { await api(`/api/skills/${encodeURIComponent(button.dataset.approve)}/approve`, {method:"POST", body:JSON.stringify({content_hash:button.dataset.hash})}); await loadAll(); toast("当前写作能力版本已授权"); } catch(error) { toast(error.message); } }));
}
$("#refresh").addEventListener("click", () => loadAll().then(() => toast("已刷新")));
loadAll().catch(error => toast(error.message));
