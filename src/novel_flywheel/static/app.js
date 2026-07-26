const state = { projects: [], trash: [], providers: [], skills: [], wizards: [], references: [], mechanisms: [], projectLearning:null, learningReport:null, referenceTask:null, referenceTaskTimer:null, localNlp:null, workflowAnalysis:null, market:null, marketBaselines:[], marketBaseline:null, marketMatch:null, activeReference: null, referenceContent: "", referenceAnalysis: null, activeProject: null, activeWizard: null, wizardStep: 0, activeRun: null, pollTimer: null, interviewWizardId: null, interviewMessages: [], interviewBusy: false, editingProviderId: null, storyState: null, materials: null, activeCharacter: null, activeMaterialGroup:"characters", activeMaterialPath:null };
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
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));
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
    return `<button class="reference-list-item ${item.id === state.activeReference.id ? "active" : ""}" data-reference-id="${item.id}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.platform||"未指定平台")} · ${escapeHtml(typeLabels[item.content_type]||"参考作品")}${linked?` · 关联《${escapeHtml(linked.title)}》`:""}</span><span>${Number(item.latest_version?.character_count || 0).toLocaleString()} 字符 · ${item.versions.length} 个版本</span></button>`;
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
  state.referenceTask = null;
  clearTimeout(state.referenceTaskTimer);
  state.referenceContent = "";
  renderReferences();
  loadReferenceAnalysisTask(sourceId);
}

async function loadReferenceContent(sourceId) {
  $("#reference-detail").innerHTML = '<p class="skill-meta">正在读取本地原文...</p>';
  try {
    const content = await api(`/api/references/${sourceId}/content`);
    if (state.activeReference?.id !== sourceId) return;
    state.referenceContent = content.text;
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
  if(!task||task.status==="idle")return `<div><strong>分析状态</strong><p>选择本地诊断、本地提炼或模型深度分析后，这里会持续显示进度和结果。</p></div>`;
  const labels={queued:"等待分析",running:"正在分析",completed:"分析完成",failed:"分析失败",cancelled:"已停止"};
  const phases={starting:"正在准备全文",analyzing_windows:"正在逐段分析全文",fallback_window:"首选模型结果无效，正在使用已配置的备用模型分析当前窗口",synthesizing:"正在合并全文结论",fallback_synthesis:"首选模型汇总结果无效，正在使用已配置的备用模型汇总",completed:"结果已经生成",failed:"任务未能完成",cancelled:"任务已停止",local_analysis:"正在扫描全文问题",local_learning:"正在提炼全文写法"};
  const total=Number(task.total_windows||0),done=Number(task.completed_windows||0);
  const elapsedEnd=task.finished_at?Date.parse(task.finished_at):Date.now();
  const elapsed=task.started_at?Math.max(0,Math.floor((elapsedEnd-Date.parse(task.started_at))/1000)):0;
  const elapsedText=elapsed>=60?`${Math.floor(elapsed/60)}分${String(elapsed%60).padStart(2,"0")}秒`:`${elapsed}秒`;
  const showIndeterminate=["queued","running"].includes(task.status);
  const progress=total?`<progress max="${total}" value="${done}"></progress><span>${done} / ${total} 个文本窗口</span>`:showIndeterminate?'<progress></progress>':"";
  const result=task.status==="completed"?`<p>结果：${task.summary||`已完成 ${done||total||1} 个处理步骤`}。你现在可以查看下方结果，再决定是否保留或应用。</p>`:task.status==="failed"?`<p>原因：${escapeHtml(task.error||"未知错误")}。已有本地内容不会丢失，可以重新尝试。</p>`:"";
  const stop=task.id&&["queued","running"].includes(task.status)?`<button class="secondary" data-reference-task-cancel="${task.id}">停止分析</button>`:"";
  return `<div><strong>${labels[task.status]||"分析状态"}</strong><p>${phases[task.phase]||"正在处理"} · 已用时 ${elapsedText}</p>${progress}${result}</div>${stop}`;
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
  const report = state.referenceAnalysis?.result;
  const metrics = report?.metrics;
  const findings = report?.findings || [];
  const learning=state.learningReport?.source_id===source.id?state.learningReport:null;
  const learningSummary=learning?`<section class="reference-learning-summary"><div><strong>${learning.analyzed_windows} / ${learning.window_count}</strong><span>窗口已扫描</span></div><div><strong>${learning.coverage_percent}%</strong><span>全文覆盖率</span></div><div><strong>${learning.mechanisms.length}</strong><span>合并后候选机制</span></div><p>本地规则已覆盖全文；候选机制的多处证据已合并，可在下方项目学习区查看。</p></section>`:"";
  const diagnosticsHtml=metrics?`<section class="reference-metrics"><div><strong>${metrics.sentence_count}</strong><span>句子</span></div><div><strong>${metrics.paragraph_count}</strong><span>段落</span></div><div><strong>${metrics.average_sentence_length}</strong><span>平均句长</span></div><div><strong>${findings.length}</strong><span>需要你复核</span></div></section><section class="reference-findings"><h3>本地诊断</h3><p class="section-intro">这些是本地规则找到的疑似位置，不代表文章一定有错。请结合原文决定是否修改。</p>${findings.length?findings.map(renderDiagnosticFinding).join(""):'<p class="skill-meta">当前没有发现需要你复核的问题。</p>'}</section>`:'<section><p class="skill-meta">尚未运行本地诊断。点击后会扫描全文，并说明每个疑似问题为什么值得检查。</p></section>';
  $("#reference-detail").innerHTML = `<header><div><p class="eyebrow">${escapeHtml(source.source_type.toUpperCase())}</p><h2>${escapeHtml(source.title)}</h2><p class="skill-meta">${Number(source.latest_version?.character_count || 0).toLocaleString()} 字符 · 版本 ${source.latest_version?.version || 1}</p></div><div class="reference-actions"><button class="primary" data-reference-create>从此资料创建作品</button><button class="secondary" data-reference-analyze>本地诊断</button><button class="secondary" data-reference-learn>本地提炼</button><button class="secondary" data-reference-model-learn>模型深度分析</button><button class="secondary danger-text" data-reference-delete>删除</button></div></header><section class="reference-task-status" data-reference-task-status></section>${learningSummary}${diagnosticsHtml}<details class="reference-source"><summary>查看原文</summary><pre>${escapeHtml(state.referenceContent)}</pre></details>`;
  renderReferenceTaskStatus();
  $("#reference-detail [data-reference-analyze]").addEventListener("click", analyzeReference);
  $("#reference-detail [data-reference-learn]").addEventListener("click", learnReference);
  $("#reference-detail [data-reference-model-learn]").addEventListener("click", modelLearnReference);
  $("#reference-detail [data-reference-create]").addEventListener("click", startWizardFromReference);
  $("#reference-detail [data-reference-delete]").addEventListener("click", deleteReference);
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
    ? `<div><p class="eyebrow">MARKET LINK</p><h3>已关联《${escapeHtml(context.title)}》</h3><p class="skill-meta">${escapeHtml(context.platform)} · ${escapeHtml(context.current?.ranking_name||"暂无当前榜单")} ${context.current?.rank?`第 ${context.current.rank} 名`:""} · 市场数据 ${escapeHtml(formatLocalTimestamp(context.current?.captured_at)||"尚未更新")}</p></div><button class="secondary danger-text" data-market-unlink>解除榜单关联</button>`
    : `<div><p class="eyebrow">MARKET MATCH</p><h3>榜单作品匹配</h3><p class="skill-meta">根据文件名、作品名和正文开头在本地查找候选，不会自动关联。</p></div><button class="secondary" data-market-match>查找榜单匹配</button><div class="market-match-results" data-market-match-results></div>`;
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
    shell.innerHTML='<p class="skill-meta">当前榜单索引没有找到候选，可继续作为普通 TXT 使用。</p>';
    return;
  }
  const label=result.status==="high"?"高度可信":"需要确认";
  shell.innerHTML=`<p class="market-match-label">${label}</p>${result.candidates.map(item=>`<article><div><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(item.platform)} · ${escapeHtml(item.ranking_name||"榜单")} · ${escapeHtml(item.category||"未分类")}</span><small>${item.reasons.map(escapeHtml).join(" · ")}</small></div><button class="primary" data-market-link="${escapeHtml(item.work_id)}">确认关联</button></article>`).join("")}`;
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
  if(!confirm("解除榜单关联？TXT 正文和资料分类会继续保留。"))return;
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
      task.summary=`全文模型分析完成，得到 ${task.result?.mechanisms?.length||0} 个候选写法`;
      renderLearning();
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
  button.textContent = "导入中...";
  status.textContent = url ? "正在读取网页内容，公开网页最多等待约 20 秒；会员或动态页面可能无法直接提取。" : "正在导入学习库...";
  try {
    let source;
    if (url) source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:"url",source_uri:url,...metadata})});
    else if (file && extension !== "txt") source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:extension,source_uri:file.name,data_base64:await fileBase64(file),...metadata})});
    else source = await api("/api/references", {method:"POST", body:JSON.stringify({title, text, source_type:file ? "txt" : "paste",...metadata})});
    event.target.reset(); state.activeReference = source; state.referenceContent = ""; state.referenceAnalysis = null;
    state.marketMatch=await api(`/api/market/references/${source.id}/match`).catch(()=>null);
    status.textContent = "";
    await loadAll(); toast(state.marketMatch?.candidates?.length?"参考资料已导入，并发现榜单匹配候选":"参考资料已导入");
  } catch(error) {
    status.textContent = `导入失败：${error.message}`;
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
  select.innerHTML=state.marketBaselines.length?state.marketBaselines.map((item,index)=>{const key=item.key;return `<option value="${index}">${escapeHtml(key.platform)} · ${escapeHtml(key.ranking_name)} · ${escapeHtml(key.category)} · ${escapeHtml(key.length_type)}（${item.sample_count}篇，${labels[item.confidence_level]}）</option>`;}).join(""):'<option value="">暂无可用样本组</option>';
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
  $("#market-baseline-detail").innerHTML=`<div class="market-baseline-summary"><div><strong>${data.sample_count}</strong><span>有效作品</span></div><div><strong>${labels[data.confidence_level]}</strong><span>可信状态</span></div><div><strong>${escapeHtml(data.date_range?`${data.date_range.start} 至 ${data.date_range.end}`:"暂无")}</strong><span>样本日期</span></div></div><div class="market-baseline-opening"><span>前500字明确问题 <strong>${data.opening.question_percent}%</strong></span><span>前500字异常信号 <strong>${data.opening.anomaly_percent}%</strong></span></div>${mechanisms.length?`<div class="market-baseline-mechanisms">${mechanisms.map(item=>`<article><div><strong>${escapeHtml(item.name)}</strong><span>${item.work_count}/${data.sample_count}篇 · ${item.prevalence_percent}%</span></div><small>${item.position_median===null?"暂无稳定位置":`全文中位位置 ${item.position_median}%`}</small></article>`).join("")}</div>`:'<p class="market-empty">当前样本尚未完成本地提炼，暂无可汇总机制。</p>'}<p class="market-baseline-boundary">${escapeHtml(data.boundary)}</p>`;
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
    ["有效快照",summary.snapshot_count+" 次"],["已关联 TXT",summary.linked_count+" 份"],
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
  if(!state.activeReference||!confirm("这是什么：模型会逐段阅读全文，再整理成需要你确认的候选写法。\n\n为什么现在询问：这个操作会调用已配置 API，可能产生费用。\n\n操作后会发生什么：分析结果只进入候选区，不会自动修改正文或写作项目。\n\n开始模型深度分析？"))return;
  try{
    state.referenceTask=await api(`/api/references/${state.activeReference.id}/model-learn`,{method:"POST"});renderReferenceTaskStatus();
    pollReferenceAnalysisTask(state.activeReference.id);
  }catch(error){state.referenceTask={status:"failed",phase:"failed",started_at:new Date().toISOString(),error:error.message};renderReferenceTaskStatus();toast(error.message);}
}

async function loadProjectLearning() {
  const projectId=$("#learning-project").value;
  state.projectLearning=projectId ? await api(`/api/projects/${projectId}/learning`) : null;
  renderLearningArtifacts();
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

function renderMechanismCard(item,adopted,rejectedView){
  const rejected=item.status==="rejected",confirmed=item.status==="confirmed";
  const needsConfirm=Number(item.data.confidence||0)<0.7&&!confirmed;
  const statusLabel=rejected?"已拒绝":confirmed?"已确认":"等待你判断";
  const evidence=item.evidence||[],positions=item.data.positions||[];
  const stages=[...new Set(positions.map(mechanismStage))];
  const groups=mechanismEvidenceGroups(item);
  const conditions=(item.data.incompatible_conditions||[]).join("；")||"当情节没有产生新信息、人物选择或关系变化时，不要为了模仿而硬加。";
  const groupedEvidence=Object.entries(groups).map(([stage,items])=>`<section><strong>${stage} · ${items.length} 处</strong>${items.map(value=>`<blockquote class="mechanism-evidence">${escapeHtml(value.excerpt)}</blockquote>`).join("")}</section>`).join("");
  return `<article class="mechanism-item">${rejectedView?`<label class="mechanism-select"><input type="checkbox" data-mechanism-select="${item.id}"> 选择</label>`:""}<header><div><h3>${escapeHtml(item.data.name)}</h3><span class="mechanism-status">${statusLabel}</span></div><p><strong>这是什么：</strong>系统从参考作品中归纳出的候选写法，还没有自动进入你的作品。</p></header><div class="mechanism-stage-summary"><strong>全文命中 ${evidence.length||positions.length||1} 处</strong><span>${stages.length?`主要分布在${stages.join("、")}`:escapeHtml(item.data.structural_position||"位置待确认")}</span><span>参考可信度 ${Math.round(Number(item.data.confidence||0)*100)}%</span></div><div class="mechanism-explanation"><section><span>原文是怎么写的</span><p>${escapeHtml(item.data.fact||"模型从多处原文证据中归纳了这一写法。")}</p></section><section><span>为什么值得学习</span><p>${escapeHtml(item.data.interpretation||item.data.emotional_effect||"它可能影响读者对信息、人物或情节推进的感受。")}</p></section><section><span>你的作品可以怎么用</span><p>${escapeHtml(item.data.transfer_guidance||"保留这种写法的作用，替换人物、设定、情节和具体表达。")}</p></section><section><span>什么时候不要用</span><p>${escapeHtml(conditions)}</p></section></div>${evidence[0]?`<section class="mechanism-representative"><span>代表证据</span><blockquote class="mechanism-evidence">${escapeHtml(evidence[0].excerpt)}</blockquote></section>`:""}${evidence.length>1?`<details class="mechanism-evidence-list"><summary>按文章阶段查看全部证据（${evidence.length} 处）</summary>${groupedEvidence}</details>`:""}<p class="mechanism-decision"><strong>你需要决定：</strong>“保留为候选”表示认可这条分析；“应用到当前作品”会把它写入当前作品的创作蓝图，但不会直接改正文；“不采用”会把它移到已拒绝列表。</p><div class="mechanism-actions"><button class="secondary" data-mechanism-confirm="${item.id}" ${(confirmed||rejected)?"disabled":""}>${confirmed?"已保留":rejected?"已拒绝":"保留为候选"}</button><button class="primary" data-mechanism-adopt="${item.id}" ${(adopted.has(item.id)||needsConfirm||rejected)?"disabled":""}>${adopted.has(item.id)?"已应用":"应用到当前作品"}</button><button class="secondary" data-mechanism-reject="${item.id}" ${rejected?"disabled":""}>${rejected?"已拒绝":"不采用"}</button>${rejected?`<button class="secondary danger-text" data-mechanism-delete="${item.id}">永久删除</button>`:""}</div></article>`;
}

function renderLearning() {
  const select=$("#learning-project"); if (!select) return;
  select.innerHTML=state.projects.length ? state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("") : '<option value="">请先创建作品</option>';
  if (state.activeProject) select.value=state.activeProject.id;
  const adopted=new Set((state.projectLearning?.adoptions||[]).map(item=>item.node_id));
  const rejectedView=$("#learning-mechanism-view")?.value==="rejected";
  const batch=rejectedView&&state.mechanisms.length?'<div class="mechanism-batch-actions"><label><input type="checkbox" data-mechanism-select-all> 全选当前结果</label><button class="secondary danger-text" data-mechanism-delete-selected>删除所选</button></div>':"";
  const cards=state.mechanisms.length?state.mechanisms.map(item=>renderMechanismCard(item,adopted,rejectedView)).join(""):`<p class="skill-meta">${rejectedView?"暂无已拒绝机制":"暂无候选机制"}</p>`;
  $("#learning-mechanisms").innerHTML=batch+cards;
  document.querySelectorAll("[data-mechanism-confirm]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismConfirm,"confirm")));
  document.querySelectorAll("[data-mechanism-adopt]").forEach(button=>button.addEventListener("click",()=>adoptMechanism(button.dataset.mechanismAdopt)));
  document.querySelectorAll("[data-mechanism-reject]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismReject,"reject")));
  document.querySelectorAll("[data-mechanism-delete]").forEach(button=>button.addEventListener("click",()=>deleteRejectedMechanisms([button.dataset.mechanismDelete])));
  $("[data-mechanism-delete-selected]")?.addEventListener("click",()=>deleteRejectedMechanisms([...document.querySelectorAll("[data-mechanism-select]:checked")].map(item=>item.dataset.mechanismSelect)));
  $("[data-mechanism-select-all]")?.addEventListener("change",event=>document.querySelectorAll("[data-mechanism-select]").forEach(item=>item.checked=event.target.checked));
  if (select.value && !state.projectLearning) loadProjectLearning(); else renderLearningArtifacts();
}
const mechanismView=()=>$("#learning-mechanism-view")?.value||"active";
async function reloadMechanisms(){state.mechanisms=await api(`/api/learning/mechanisms?view=${encodeURIComponent(mechanismView())}`);renderLearning();}
async function reviseMechanism(id,action) { try { await api(`/api/learning/nodes/${id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})}); await reloadMechanisms(); toast(action==="confirm"?"分析已确认":"分析已拒绝，可在“已拒绝”中查看"); } catch(error){toast(error.message);} }
async function deleteRejectedMechanisms(ids){if(!ids.length)return toast("请先选择要删除的记录");if(!confirm(`永久删除 ${ids.length} 条已拒绝机制及其证据？此操作不可撤销。`))return;try{const result=await api("/api/learning/mechanisms",{method:"DELETE",body:JSON.stringify({node_ids:ids})});await reloadMechanisms();const skipped=result.skipped.length?`，${result.skipped.length} 条因已采纳或状态不符未删除`:"";toast(`已删除 ${result.deleted_ids.length} 条${skipped}`);}catch(error){toast(error.message);}}
async function adoptMechanism(id) { const projectId=$("#learning-project").value; if(!projectId)return toast("请先选择作品"); try { await api(`/api/projects/${projectId}/learning/adoptions/${id}`,{method:"POST",body:JSON.stringify({edits:{}})}); await loadProjectLearning(); renderLearning(); toast("已采纳并生成新版创作蓝图"); } catch(error){toast(error.message);} }
function renderLearningArtifacts(){
  const shell=$("#learning-artifacts"); if(!shell)return;
  const artifacts=state.projectLearning?.artifacts||[];
  const reviews=state.projectLearning?.adoption_reviews||[];
  const warning=reviews.length?`<section class="material-audit-status"><strong>有 ${reviews.length} 条已采纳机制需要重新确认</strong><p>来源资料的平台、内容类型或关联作品已修改。请在上方重新采纳需要保留的机制；正式正文不会被自动修改。</p>${reviews.map(item=>`<p>· ${escapeHtml(item.mechanism?.name||item.node_id)}</p>`).join("")}</section>`:"";
  const content=artifacts.length?artifacts.map(item=>`<details class="learning-artifact" open><summary><strong>${escapeHtml(learningArtifactLabels[item.artifact_type]||item.artifact_type)}</strong><span>版本 ${item.version} · ${item.status==="stale"?"待复核":"生效中"}</span></summary><div class="project-learning-copy">${readableLearningValue(item.data)}</div></details>`).join(""):'<p class="skill-meta">采纳机制或建立文笔资料后在此显示</p>';
  shell.innerHTML=warning+content;
}
$("#learning-project").addEventListener("change",async event=>{ state.activeProject=state.projects.find(item=>item.id===event.target.value)||state.activeProject; state.projectLearning=null; await loadProjectLearning(); renderLearning(); });
$("#learning-mechanism-view").addEventListener("change",reloadMechanisms);
const learningProjectId=()=>$("#learning-project").value;
async function saveLearningArtifact(path,data){const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/${path}`,{method:"PUT",body:JSON.stringify({data})});await loadProjectLearning();toast("已保存为新版本");}catch(error){toast(error.message);}}
$("#baseline-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);await saveLearningArtifact("prose-baseline",{dialogue:form.get("dialogue"),psychology:form.get("psychology"),forbidden_patterns:String(form.get("forbidden")||"").split(/\r?\n/).map(item=>item.trim()).filter(Boolean)});});
$("#voice-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);const current=state.projectLearning?.artifacts?.find(item=>item.artifact_type==="voice_profiles")?.data||{};await saveLearningArtifact("voice-profiles",{...current,[form.get("name")]:{rules:form.get("profile")}});});
$("#scene-brief-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/scene-briefs`,{method:"POST",body:JSON.stringify({outline:new FormData(event.target).get("outline")})});await loadProjectLearning();toast("场景简报已生成，可继续编辑");}catch(error){toast(error.message);}});
$("#outline-candidate-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId||!confirm("将调用规划模型生成候选大纲，不会覆盖现有大纲。继续？"))return;try{const result=await api(`/api/projects/${projectId}/learning/generate-outline`,{method:"POST",body:JSON.stringify({brief:new FormData(event.target).get("brief")})});toast(`候选大纲已保存：${result.id}`);}catch(error){toast(error.message);}});
$("#line-edit-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId||!confirm("将调用 line_edit 模型生成候选文本，不会修改正式正文。继续？"))return;const form=new FormData(event.target);try{const result=await api(`/api/projects/${projectId}/learning/model-line-edit`,{method:"POST",body:JSON.stringify({source:form.get("source"),issues:String(form.get("issues")).split(/[,，]/).map(item=>item.trim()).filter(Boolean),locked_facts:[],adjacent_context:""})});const shell=$("#line-edit-result");shell.hidden=false;shell.textContent=result.candidate;toast("精修候选已生成，原文未修改");}catch(error){toast(error.message);}});

function renderNlpStatus(){ if(!state.localNlp)return; $("#nlp-status").textContent=`${state.localNlp.installed?"已安装":"未安装"} · ${state.localNlp.enabled?"已启用":"未启用"} · ${state.localNlp.operation} · ${state.localNlp.download_notice}`; $("#nlp-toggle").textContent=state.localNlp.enabled?"停用":"启用"; }
async function nlpAction(path,options={method:"POST"}){ try{state.localNlp=await api(path,options);renderNlpStatus();toast("本地 NLP 状态已更新");}catch(error){toast(error.message);} }
$("#nlp-install").addEventListener("click",()=>nlpAction("/api/settings/local-nlp/install"));
$("#nlp-uninstall").addEventListener("click",()=>confirm("卸载 LTP 本地分析组件？")&&nlpAction("/api/settings/local-nlp/uninstall"));
$("#nlp-toggle").addEventListener("click",()=>nlpAction("/api/settings/local-nlp",{method:"PUT",body:JSON.stringify({enabled:!state.localNlp?.enabled})}));
async function loadWorkflowAnalysis(){
  const shell=$("#workflow-analysis-status"),button=$("#workflow-analysis-toggle");
  if(!state.activeProject){state.workflowAnalysis=null;shell.textContent="请选择作品";button.disabled=true;return;}
  state.workflowAnalysis=await api(`/api/projects/${state.activeProject.id}/learning/workflow-analysis`);
  button.disabled=false;button.textContent=state.workflowAnalysis.enabled?"停用当前作品优化":"为当前作品启用";
  shell.textContent=state.workflowAnalysis.enabled?"已启用 · 首次全文终审，返修后关联窗口复核 · 原创范围 local_corpus_only":"未启用 · 继续使用每轮全文终审";
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
async function loadCandidateQuality(projectId) {
  const shell = $("#candidate-quality"); const publish = $("#publish-candidate");
  publish.hidden = true;
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/candidate`);
    if (state.activeProject?.id !== projectId) return;
    if (!result.available) { shell.innerHTML = '<p class="skill-meta">尚无候选稿</p>'; return; }
    const report = result.diagnostics;
    const originality=result.analysis?.originality||{}; const nlp=result.analysis?.nlp||{}; const ledger=result.analysis?.narrative_ledger||{};
    const unresolved=[...(ledger.promises||[]),...(ledger.questions||[]),...(ledger.setups||[])].filter(item=>item.status==="unresolved");
    const ledgerHtml=`<details class="quality-ledger"><summary><span><strong>叙事账本</strong><small>未兑现 ${unresolved.length} · 已关联 ${(ledger.relations||[]).length} · 场景 ${(ledger.scenes||[]).length}</small></span><span>查看证据</span></summary><div class="ledger-list">${unresolved.slice(0,8).map(item=>`<details><summary><span class="ledger-status">待回应</span>${escapeHtml(item.kind||"线索")} · 位置 ${Number(item.start||0).toLocaleString()}</summary><p>${escapeHtml(item.text||"")}</p></details>`).join("")||'<p class="skill-meta">显式问题、承诺与伏笔均已找到后文回应；语义不确定项仍由终审模型复核。</p>'}</div></details>`;
    shell.innerHTML = `<div class="candidate-metrics"><div><strong>${report.naturalness_score}</strong><span>自然度</span></div><div><strong>${report.blocking_count}</strong><span>阻断问题</span></div><div><strong>${report.targeted_count}</strong><span>局部优化项</span></div><div><strong>${Number(result.effective_words).toLocaleString()}</strong><span>正文有效字数 · 纯汉字 ${Number(result.han_characters).toLocaleString()} · 总字符 ${Number(result.characters).toLocaleString()}</span></div></div><p class="skill-meta">全文扫描 ${escapeHtml(result.analysis_status)} · LTP ${nlp.available?"已完成":"规则降级"} · 原创检查仅限本地语料（${escapeHtml(result.review_scope||"local_corpus_only")}） · 连续片段 ${Number(originality.continuous_passages?.length||0)} · 人名 ${Number(originality.similar_names?.length||0)} · 语义候选 ${Number(originality.semantic_candidates?.length||0)}</p>${report.findings.length ? `<div class="candidate-findings">${report.findings.slice(0,5).map(item => `<p><strong>${escapeHtml(item.code)}</strong><span>第 ${item.segment} 段 · ${escapeHtml(item.excerpt)}</span></p>`).join("")}</div>` : '<p class="skill-meta">本地扫描未发现明显模板化问题</p>'}${ledgerHtml}`;
    publish.hidden = state.activeProject?.mode !== "short" || report.blocking_count > 0;
  } catch(error) { shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`; }
}
async function loadWritingRulesSummary(projectId) {
  const shell = $("#writing-rules-summary");
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/learning`);
    if (state.activeProject?.id !== projectId) return;
    const baseline = result.artifacts.find(item => item.artifact_type === "prose_baseline");
    if (!baseline) { shell.innerHTML = '<p class="skill-meta">尚未建立文笔基线，请前往学习库分析并采纳参考资料。</p>'; return; }
    const labels = {sentence_rhythm:"句式与节奏",dialogue:"对白",narrative_distance:"叙事距离",psychology:"心理描写",professional_detail:"用词与细节",forbidden_patterns:"避免"};
    const entries = Object.entries(labels).filter(([key]) => baseline.data[key]?.length || typeof baseline.data[key] === "string" && baseline.data[key]);
    shell.innerHTML = `<div><strong>${escapeHtml(baseline.data.summary || "已启用项目文笔基线")}</strong><span class="skill-meta">版本 ${baseline.version}${result.legacy_style_migration?.migrated ? " · 已迁移旧范文笔感" : ""}</span></div><div class="writing-rule-list">${entries.map(([key,label]) => `<p><strong>${label}</strong><span>${escapeHtml(Array.isArray(baseline.data[key]) ? baseline.data[key].join("；") : baseline.data[key])}</span></p>`).join("")}</div>`;
  } catch(error) { shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`; }
}
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
      toast(`资料已保存 · StoryState 版本 ${result.story_state_revision}`); await renderMaterials();
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
const learningArtifactLabels={creative_blueprint:"创作蓝图",prose_baseline:"可执行文笔基线",voice_profiles:"人物声音档案",epistemic_state:"人物认知状态",scene_briefs:"场景简报"};
const learningFieldLabels={status:"状态",mechanisms:"已采纳机制",rules:"执行规则",summary:"摘要",sentence_rhythm:"句子节奏",paragraph_rhythm:"段落节奏",dialogue:"对白规则",psychology:"心理描写",narrative_distance:"叙事距离",viewpoint:"视角",action_sensation:"动作与感官",professional_detail:"专业细节",forbidden_patterns:"禁止表达",states:"认知记录",briefs:"场景",name:"名称",fact:"事实",interpretation:"分析",transfer_guidance:"迁移方式",title:"标题",pov:"视角",entry_goal:"入场目标",obstacle:"阻碍",relationship_tension:"关系张力",required_state_change:"必要变化",information_boundary:"信息边界",reader_question:"读者问题",exit_state:"离场状态",locked_facts:"锁定事实",source:"来源",provenance:"依据"};
function readableLearningValue(value,key="") {
  if (value===null || value===undefined || value==="") return '<span class="skill-meta">未设置</span>';
  if (Array.isArray(value)) return value.length ? `<ul>${value.map(item=>`<li>${typeof item==="object"?readableLearningValue(item):escapeHtml(item)}</li>`).join("")}</ul>` : '<span class="skill-meta">暂无</span>';
  if (typeof value==="object") return `<dl>${Object.entries(value).map(([name,item])=>`<div><dt>${escapeHtml(learningFieldLabels[name]||name)}</dt><dd>${readableLearningValue(item,name)}</dd></div>`).join("")}</dl>`;
  if (key==="status") return escapeHtml({candidate:"候选",active:"生效中",stale:"待复核"}[value]||value);
  return `<span>${escapeHtml(value)}</span>`;
}
function renderProjectLearningMaterials(result) {
  const shell=$("#project-learning-materials"); if(!shell)return;
  if(!result){shell.innerHTML='<p class="skill-meta">请选择作品</p>';return;}
  const artifacts=result.artifacts||[], adoptions=result.adoptions||[];
  const sections=artifacts.map(item=>`<details class="project-learning-item" open><summary><strong>${escapeHtml(learningArtifactLabels[item.artifact_type]||item.artifact_type)}</strong><span>版本 ${item.version} · ${item.status==="stale"?"待复核":"生效中"}</span></summary><div class="project-learning-copy">${readableLearningValue(item.data)}</div></details>`);
  if(adoptions.length) sections.splice(1,0,`<details class="project-learning-item" open><summary><strong>已采纳机制</strong><span>${adoptions.length} 项</span></summary><div class="project-learning-copy">${readableLearningValue(adoptions.map(item=>item.data))}</div></details>`);
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
  try { const result=await api(`/api/projects/${state.activeProject.id}/material-impacts/${impactId}/apply`,{method:"POST",body:JSON.stringify({proposal_ids:proposalIds})}); toast(`关联资料已更新 · StoryState 版本 ${result.story_state_revision}`); await renderMaterials(); }
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
  let value; try { value=JSON.parse($("#story-state-value").value); } catch { return toast("项目资料必须是有效 JSON"); }
  const section=$("#story-state-section").value;
  try {
    state.storyState=await api(`/api/projects/${state.activeProject.id}/story-state`,{method:"PUT",body:JSON.stringify({expected_revision:state.storyState.revision,section,value})});
    $("#story-state-revision").textContent=`版本 ${state.storyState.revision} · 已保存人工修改`;
    renderStoryStateSection(); toast("项目资料已保存为新版本");
  } catch(error) { toast(error.message); await loadStoryState(state.activeProject.id); }
});
$("#publish-candidate").addEventListener("click", async () => {
  if (!state.activeProject || !confirm("将当前最高分候选设为正式成品？原正式成品会被替换。")) return;
  try {
    await api(`/api/projects/${state.activeProject.id}/candidate/publish`, {method:"POST"});
    toast("候选稿已设为正式成品");
    await Promise.all([loadProjectLocations(state.activeProject.id), loadCandidateQuality(state.activeProject.id)]);
  } catch(error) { toast(error.message); }
});
async function renderActiveProject() {
  const p = state.activeProject;
  $("#short-actions").hidden = !p || p.mode !== "short"; $("#long-actions").hidden = !p || p.mode !== "long";
  $("#project-summary").innerHTML = p ? `<div class="metric"><strong>${escapeHtml(p.title)}</strong><span>当前作品</span></div><div class="metric"><strong>${p.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(p.target_words).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${escapeHtml(p.genre)}</strong><span>题材</span></div>` : '<span>先创建一部作品。</span>';
  $("#trash-project").disabled = !p;
  if (!p) { $("#run-list").innerHTML = ""; await loadProjectLocations(null); await loadCandidateQuality(null); await loadWritingRulesSummary(null); await loadWorkflowAnalysis(); return; }
  await Promise.all([loadProjectLocations(p.id), loadCandidateQuality(p.id), loadWritingRulesSummary(p.id), loadWorkflowAnalysis()]);
  const runs = await api(`/api/projects/${p.id}/runs`);
  const initialization = runs.find(run => run.workflow === "initialize-skills");
  const initializing = initialization && ["queued","running","cancelling"].includes(initialization.status);
  const initialized = initialization?.status === "completed";
  const activeRun = runs.find(run => ["queued","running","cancelling"].includes(run.status));
  const latestRun = runs[0];
  $("#initialize-project").hidden = initialized || initializing;
  ["#run-short", "#run-setup", "#run-chapter"].forEach(selector => { $(selector).disabled = !initialized; });
  $("#run-list").innerHTML = runs.length ? runs.map(r => `<button class="run-row" data-run-detail="${r.id}"><div><strong>${escapeHtml(r.workflow)}</strong><div class="skill-meta">${escapeHtml(r.current_stage || "-")} · ${escapeHtml(formatLocalTimestamp(r.created_at))}</div></div><span class="status ${isQualityRejected(r) ? "quality-rejected" : r.status}">${escapeHtml(runStatusLabel(r))}</span></button>`).join("") : '<p class="skill-meta">暂无运行记录</p>';
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
  if (field.id === "market_baseline_key") return `<select class="field-value"><option value="">暂不选择</option>${state.marketBaselines.map(item=>{const serialized=JSON.stringify(item.key);const label={insufficient:"样本不足",preliminary:"初步",advisory:"可用于建议"}[item.confidence_level];return `<option value="${escapeHtml(serialized)}" ${serialized===value?"selected":""}>${escapeHtml(item.key.platform)} · ${escapeHtml(item.key.category)} · ${escapeHtml(item.key.ranking_name)} · ${escapeHtml(item.key.length_type)}（${item.sample_count}篇，${label}）</option>`;}).join("")}</select>`;
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
  $("#wizard-source").textContent = step.skill_name ? `${step.skill_name} · ${step.skill_hash.slice(0,12)}` : "CORE REQUIREMENTS";
  $("#wizard-fields").innerHTML = step.fields.map(field => { const answer = wizard.answers[field.id] || {}; return `<div class="wizard-field" data-field="${escapeHtml(field.id)}" data-type="${field.type}"><label><span>${escapeHtml(field.label)}${field.required ? " *" : ""}</span>${fieldControl(field,answer)}</label>${field.lockable ? `<label class="policy-label">处理方式<select class="field-policy"><option value="locked" ${answer.policy === "locked" ? "selected" : ""}>严格锁定</option><option value="suggestible" ${!answer.policy || answer.policy === "suggestible" ? "selected" : ""}>可建议</option><option value="generated" ${answer.policy === "generated" ? "selected" : ""}>模型生成</option></select></label>` : ""}</div>`; }).join("");
  updateGenreOptions();
  document.querySelector('[data-field="genre"] .field-value')?.addEventListener("input", updateGenreOptions);
  updateMarketBaselineWizardState();
  document.querySelector('[data-field="market_baseline_enabled"] .field-value')?.addEventListener("change",updateMarketBaselineWizardState);
  document.querySelector('[data-field="platform"] .field-value')?.addEventListener("change",recommendMarketBaseline);
  document.querySelector('[data-field="genre"] .field-value')?.addEventListener("change",recommendMarketBaseline);
  $("#wizard-back").disabled = state.wizardStep === 0; $("#wizard-next").hidden = state.wizardStep === steps.length - 1; $("#wizard-analyze").hidden = state.wizardStep !== steps.length - 1; $("#wizard-confirm").hidden = state.wizardStep !== steps.length - 1;
  document.querySelectorAll("[data-wizard-step]").forEach(button => button.addEventListener("click", async () => { await saveWizardStep(); state.wizardStep = Number(button.dataset.wizardStep); renderWizard(); }));
  let timer; document.querySelectorAll(".field-value,.field-policy").forEach(control => control.addEventListener("input", () => { $("#wizard-save-state").textContent = "保存中"; clearTimeout(timer); timer=setTimeout(() => saveWizardStep().catch(error => toast(error.message)),500); }));
  renderWizardSummary();
  if (state.interviewWizardId === wizard.id) renderInterview(); else loadInterview().catch(error => toast(error.message));
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
    state.activeWizard=wizard; state.wizardStep=0; state.wizards.unshift(wizard); showView("projects"); renderWizard();
    if(referenceId) toast("学习成果已带入建书向导，可继续修改大纲和设定");
  } catch(error) { toast(error.message); }
}
$("#start-wizard").addEventListener("click", startWizardFromReference);
$("#wizard-drafts").addEventListener("change", async event => { if (!event.target.value) return; state.activeWizard=await api(`/api/wizards/${event.target.value}`); state.wizardStep=0; renderWizard(); });
$("#wizard-back").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep--; renderWizard(); });
$("#wizard-next").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep++; renderWizard(); });
$("#wizard-analyze").addEventListener("click", async () => { try { await saveWizardStep(); state.activeWizard=await api(`/api/wizards/${state.activeWizard.id}/analyze`,{method:"POST"}); state.wizardStep=state.activeWizard.schema.steps.length-1; renderWizard(); toast(state.activeWizard.status === "ready" ? "关键资料完整" : "已生成必要追问"); } catch(error) { toast(error.message); } });
$("#wizard-confirm").addEventListener("click", async () => { try { await saveWizardStep(); const project=await api(`/api/wizards/${state.activeWizard.id}/confirm`,{method:"POST"}); state.projects.unshift(project); state.activeProject=project; state.activeWizard=null; $("#wizard-shell").hidden=true; $("#wizard-launcher").hidden=false; renderProjects(); showView("workbench"); const initialized=await api(`/api/projects/${project.id}/initialize-skills`,{method:"POST"}); monitorRun(initialized); } catch(error) { toast(error.message); } });

async function run(path, body) {
  if (!state.activeProject) return toast("请先创建作品");
  const box = $("#run-state"); box.className = "run-state busy"; box.textContent = "飞轮运行中，请保持此页面打开...";
  try { const result = await api(path, {method:"POST", body:body ? JSON.stringify(body) : undefined}); monitorRun(result); }
  catch (error) { box.className = "run-state error"; box.textContent = error.message; }
}
function renderRunLog(events) {
  $("#run-log").innerHTML = events.length ? events.map(item => {
    const message = item.message || `${item.event_type || "event"}: 未返回可用诊断信息`;
    return `<div class="log-row ${escapeHtml(item.severity)}"><span class="log-time">${escapeHtml(formatLocalTimestamp(item.created_at, true))}</span><span class="log-stage">${escapeHtml(item.stage || item.event_type)}</span><span>${escapeHtml(message)}</span></div>`;
  }).join("") : '<p class="skill-meta">等待第一条运行日志...</p>';
  $("#run-log").scrollTop = $("#run-log").scrollHeight;
}
function renderRunContext(detail) {
  const events=detail.events || []; const loaded=new Map();
  events.filter(item => item.event_type === "skills_loaded").forEach(item => loaded.set(item.stage,item.metadata || {}));
  const pendingFallbacks=new Set(); const completed=[];
  events.forEach(item => { if(item.event_type === "model_fallback") pendingFallbacks.add(item.stage); if(item.event_type === "stage_completed") { completed.push({...item,usedFallback:pendingFallbacks.has(item.stage)}); pendingFallbacks.delete(item.stage); } });
  const stages=completed.map(item => { const meta=item.metadata || {}; const context=loaded.get(item.stage) || {}; return `<div class="context-stage"><div><strong>${escapeHtml(roles[item.stage] || item.stage)}</strong><span>${escapeHtml(meta.model_name || "未记录模型")}${item.usedFallback ? " · 已回退" : ""}</span></div><dl><dt>Skill</dt><dd>${escapeHtml((context.skills || meta.skills || []).join("、") || "无")}</dd><dt>提示词</dt><dd>${Number(context.prompt_characters || 0).toLocaleString()} 字符</dd><dt>约束</dt><dd>${Number(context.constraint_characters || 0).toLocaleString()} 字符</dd><dt>Token</dt><dd>${Number(meta.input_tokens || 0).toLocaleString()} 输入 · ${Number(meta.output_tokens || 0).toLocaleString()} 输出</dd><dt>执行</dt><dd>${escapeHtml(meta.execution_mode || "普通请求")}</dd></dl></div>`; });
  const tools=detail.tool_receipts || [];
  const audit=detail.quality_report?.final_review_evidence; const counts=audit?.reconciliation_counts || {};
  const quality=audit ? `<div class="context-tools"><strong>${audit.review_mode==="incremental"?"关联窗口复核":"全文终审"}</strong><span>覆盖 ${Math.round(Number(audit.coverage || 0)*100)}% · ${Number(audit.reviewed_windows || 0)}/${Number(audit.window_count || 0)} 窗口 · 节省约 ${Number(audit.estimated_saved_input_characters || 0).toLocaleString()} 输入字符${(audit.fallback_reasons || []).length ? ` · 全文回退：${escapeHtml(audit.fallback_reasons.join("、"))}` : ""} · 已解决 ${Number(counts.resolved || 0)} · 部分解决 ${Number(counts.partially_resolved || 0)} · 未解决 ${Number(counts.unresolved || 0)}${(audit.gate_reasons || []).length ? ` · 阻断：${escapeHtml(audit.gate_reasons.join("、"))}` : ""}</span></div>` : "";
  const issues=detail.quality_report?.review?.issues||detail.quality_report?.issues||[];
  const issueLedger=issues.length?`<details class="quality-ledger"><summary><span><strong>问题返修台账</strong><small>${issues.length} 项 · 未解决优先</small></span><span>展开</span></summary><div class="ledger-list">${[...issues].sort((a,b)=>(a.status==="resolved")-(b.status==="resolved")).map(item=>`<details><summary><span class="ledger-status ${item.status==="resolved"?"resolved":""}">${item.status==="resolved"?"已解决":"待处理"}</span>${escapeHtml(item.issue_id||item.category||"问题")}</summary><p><strong>证据：</strong>${escapeHtml(item.evidence||"未提供")}</p><p><strong>修复目标：</strong>${escapeHtml(item.repair_goal||item.action||"待确认")}</p></details>`).join("")}</div></details>`:"";
  $("#run-context").innerHTML=(stages.join("") || '<p class="skill-meta">本次运行尚无已完成阶段</p>') + quality + issueLedger + (tools.length ? `<div class="context-tools"><strong>工具调用收据</strong><span>${tools.length} 条 · ${escapeHtml([...new Set(tools.map(item => item.execution_mode))].join("、"))}</span></div>` : "");
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
  $("#run-state").textContent=active ? `正在执行：${detail.current_stage || detail.workflow}` : detail.status === "completed" ? (initialization ? "初始化及校验已完成，可以开始写作" : "任务执行完成") : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : detail.status === "failed" ? `${initialization ? "初始化" : "任务"}失败：${detail.error || "请查看日志"}` : `${runStatusLabel(detail)}：${detail.error || "请查看日志"}`;
}
async function monitorRun(runRecord) {
  clearTimeout(state.pollTimer); state.activeRun=runRecord.id; $("#run-cancel").hidden=false;
  const poll = async () => {
    try {
      const detail=await api(`/api/runs/${state.activeRun}`); renderRunLog(detail.events || []); renderRunContext(detail);
      if (detail.workflow==="materials-audit") renderMaterialAudit(detail);
      const active=["queued","running","cancelling"].includes(detail.status); const qualityRejected=isQualityRejected(detail); $("#run-state").className=`run-state ${active ? "busy" : qualityRejected ? "warning" : detail.status === "failed" ? "error" : detail.status}`;
      $("#run-state").textContent=detail.status === "cancelling" ? "正在终止当前阶段..." : active ? `正在执行：${detail.current_stage || detail.workflow}` : detail.status === "completed" ? "执行完成" : detail.status === "cancelled" ? "本次任务已终止，作品仍可继续写作" : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : `${runStatusLabel(detail)}：${detail.error || "请查看日志"}`;
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
    toast(editing ? "供应商已更新" : "供应商已保存，API Key 已进入系统凭据库");
  } catch(error) { toast(error.message); }
});
$("#model-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); const provider = data.provider_id; delete data.provider_id; try { await api(`/api/providers/${provider}/models`, {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("模型映射已保存"); } catch(error) { toast(error.message); } });
function renderProviders() {
  $("#model-provider").innerHTML = state.providers.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  $("#provider-list").innerHTML = state.providers.length ? state.providers.map(p => `<div class="data-row"><div><strong>${escapeHtml(p.name)}</strong><div class="skill-meta">${escapeHtml(p.protocol)} · ${escapeHtml(p.base_url)}</div><div class="key-update"><input type="password" autocomplete="new-password" placeholder="${p.has_api_key ? "更新 API Key" : "API Key 已缺失，请重新输入"}" data-key-input="${p.id}"><button class="secondary" data-key-save="${p.id}">保存密钥</button></div>${p.models.map(m => `<div class="model-row"><strong>${escapeHtml(m.display_name)}</strong><div class="model-actions"><button class="secondary" data-probe-provider="${p.id}" data-probe-model="${m.id}" ${p.has_api_key ? "" : "disabled"}>检测模型</button><span id="probe-${m.id}" class="probe-result">${p.has_api_key ? "尚未检测" : "请先更新密钥"}</span></div></div>`).join("")}</div><div class="provider-actions"><span class="badge ${p.has_api_key ? "" : "missing"}">${p.has_api_key ? `${p.models.length} 个模型` : "密钥缺失"}</span><button class="secondary" data-provider-edit="${p.id}">编辑</button><button class="danger-button" data-provider-delete="${p.id}">删除</button></div></div>`).join("") : '<p class="skill-meta">尚未配置供应商</p>';
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
    if (!apiKey) return toast("请输入新的 API Key"); button.disabled=true;
    try { await api(`/api/providers/${button.dataset.keySave}/api-key`,{method:"PUT",body:JSON.stringify({api_key:apiKey})}); input.value=""; await loadAll(); toast("API Key 已更新，可以检测模型了"); }
    catch(error) { toast(error.message); } finally { button.disabled=false; }
  }));
  document.querySelectorAll("[data-probe-model]").forEach(button => button.addEventListener("click", async () => {
    const resultBox=$(`#probe-${button.dataset.probeModel}`); resultBox.className="probe-result"; resultBox.textContent="检测中..."; button.disabled=true;
    try { const result=await api(`/api/providers/${button.dataset.probeProvider}/models/${button.dataset.probeModel}/probe`,{method:"POST"}); const all=result.chat&&result.structured_output&&result.tool_calling; const partial=result.chat&&!all; resultBox.className=`probe-result ${all ? "success" : partial ? "partial" : "error"}`; resultBox.textContent=`连接 ${result.chat ? "✓" : "×"} · JSON ${result.structured_output ? "✓" : "×"} · 工具 ${result.tool_calling ? "✓" : "×"}${result.error ? ` · ${result.error}` : ""}`; }
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
  $("#skill-list").innerHTML = state.skills.length ? state.skills.map(s => `<div class="data-row"><div><strong>${escapeHtml(s.name)}</strong><div class="skill-meta">${escapeHtml(s.path)}<br>${s.content_hash.slice(0,16)}</div>${s.conflicts?.length ? `<div class="skill-conflicts">${s.conflicts.map(item => `<p><strong>${escapeHtml(item.code)}</strong>${escapeHtml(item.message)}</p>`).join("")}</div>` : ""}</div><div>${s.executable ? '<span class="badge">执行型</span>' : s.has_scripts ? '<span class="badge">提示词 · 含辅助脚本</span>' : '<span class="badge">提示词</span>'} ${s.conflicts?.length ? `<span class="badge conflict">冲突 ${s.conflicts.length}</span>` : ""} ${s.approved ? '<span class="status">已启用</span>' : `<button class="secondary" data-approve="${escapeHtml(s.name)}" data-hash="${s.content_hash}">授权</button>`}</div></div>`).join("") : '<p class="skill-meta">未发现 Skill</p>';
  document.querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", async () => { try { await api(`/api/skills/${encodeURIComponent(button.dataset.approve)}/approve`, {method:"POST", body:JSON.stringify({content_hash:button.dataset.hash})}); await loadAll(); toast("当前 Skill 版本已授权"); } catch(error) { toast(error.message); } }));
}
$("#refresh").addEventListener("click", () => loadAll().then(() => toast("已刷新")));
loadAll().catch(error => toast(error.message));
