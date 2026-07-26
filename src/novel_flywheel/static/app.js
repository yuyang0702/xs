const state = { projects: [], trash: [], providers: [], skills: [], wizards: [], references: [], mechanisms: [], projectLearning:null, localNlp:null, workflowAnalysis:null, activeReference: null, referenceContent: "", referenceAnalysis: null, activeProject: null, activeWizard: null, wizardStep: 0, activeRun: null, pollTimer: null, interviewWizardId: null, interviewMessages: [], interviewBusy: false, editingProviderId: null, storyState: null, materials: null, activeCharacter: null, activeMaterialGroup:"characters", activeMaterialPath:null };
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
}));
document.querySelectorAll("[data-view-target]").forEach(button => button.addEventListener("click", () => showView(button.dataset.viewTarget)));

async function loadAll() {
  [state.projects, state.trash, state.providers, state.skills, state.wizards, state.references, state.mechanisms, state.localNlp] = await Promise.all([api("/api/projects"), api("/api/projects/trash"), api("/api/providers"), api("/api/skills"), api("/api/wizards"), api("/api/references"), api("/api/learning/mechanisms"), api("/api/settings/local-nlp")]);
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
  state.referenceContent = "";
  renderReferences();
}

async function loadReferenceContent(sourceId) {
  $("#reference-detail").innerHTML = '<p class="skill-meta">正在读取本地原文...</p>';
  try {
    const content = await api(`/api/references/${sourceId}/content`);
    if (state.activeReference?.id !== sourceId) return;
    state.referenceContent = content.text;
    renderReferenceDetail();
  } catch(error) { toast(error.message); }
}

function renderReferenceDetail() {
  const source = state.activeReference;
  if (!source) return;
  const typeLabels={reference_work:"参考作品",platform_rule:"平台规则",popular_sample:"爆款样本",writing_tutorial:"写作教程",competitor_work:"竞品作品"};
  const report = state.referenceAnalysis?.result;
  const metrics = report?.metrics;
  const findings = report?.findings || [];
  $("#reference-detail").innerHTML = `<header><div><p class="eyebrow">${escapeHtml(source.source_type.toUpperCase())}</p><h2>${escapeHtml(source.title)}</h2><p class="skill-meta">${Number(source.latest_version?.character_count || 0).toLocaleString()} 字符 · 版本 ${source.latest_version?.version || 1}</p></div><div class="reference-actions"><button class="primary" data-reference-create>从此资料创建作品</button><button class="secondary" data-reference-analyze>本地诊断</button><button class="secondary" data-reference-learn>本地提炼</button><button class="secondary" data-reference-model-learn>模型深度分析</button><button class="secondary danger-text" data-reference-delete>删除</button></div></header>${metrics ? `<section class="reference-metrics"><div><strong>${metrics.sentence_count}</strong><span>句子</span></div><div><strong>${metrics.paragraph_count}</strong><span>段落</span></div><div><strong>${metrics.average_sentence_length}</strong><span>平均句长</span></div><div><strong>${findings.length}</strong><span>待复核项</span></div></section><section class="reference-findings"><h3>本地诊断</h3>${findings.length ? findings.map(item => `<article><div><strong>${escapeHtml(item.message)}</strong><span>${escapeHtml(item.rule_id)} · ${escapeHtml(item.severity)}</span></div><blockquote>${escapeHtml(item.evidence)}</blockquote><p>${escapeHtml(item.repair_goal)}</p></article>`).join("") : '<p class="skill-meta">当前本地规则未发现需要复核的问题</p>'}</section>` : '<section><p class="skill-meta">尚未运行本地诊断</p></section>'}<details class="reference-source"><summary>查看原文</summary><pre>${escapeHtml(state.referenceContent)}</pre></details>`;
  $("#reference-detail [data-reference-analyze]").addEventListener("click", analyzeReference);
  $("#reference-detail [data-reference-learn]").addEventListener("click", learnReference);
  $("#reference-detail [data-reference-model-learn]").addEventListener("click", modelLearnReference);
  $("#reference-detail [data-reference-create]").addEventListener("click", startWizardFromReference);
  $("#reference-detail [data-reference-delete]").addEventListener("click", deleteReference);
  const header=$("#reference-detail header");
  const metadata=document.createElement("section");
  metadata.className="reference-metadata";
  metadata.innerHTML=`<label>平台<input data-reference-platform maxlength="80" value="${escapeHtml(source.platform||"")}"></label><label>内容类型<select data-reference-type>${Object.entries(typeLabels).map(([value,label])=>`<option value="${value}" ${value===source.content_type?"selected":""}>${label}</option>`).join("")}</select></label><label>关联作品<select data-reference-project><option value="">不关联作品</option>${state.projects.map(item=>`<option value="${item.id}" ${item.id===source.project_id?"selected":""}>${escapeHtml(item.title)}</option>`).join("")}</select></label><button class="secondary" data-reference-metadata-save>保存分类</button>${source.content_type==="popular_sample"?'<button class="secondary" data-reference-popular>爆款分析</button>':""}`;
  header.insertAdjacentElement("afterend",metadata);
  metadata.querySelector("[data-reference-metadata-save]").addEventListener("click",saveReferenceMetadata);
  metadata.querySelector("[data-reference-popular]")?.addEventListener("click",analyzePopularReference);
}

async function saveReferenceMetadata(){
  try{
    const shell=$("#reference-detail .reference-metadata");
    const source=await api(`/api/references/${state.activeReference.id}/metadata`,{method:"PATCH",body:JSON.stringify({platform:shell.querySelector("[data-reference-platform]").value.trim()||null,content_type:shell.querySelector("[data-reference-type]").value,project_id:shell.querySelector("[data-reference-project]").value||null})});
    state.activeReference=source; await loadAll(); toast("资料分类已保存");
  }catch(error){toast(error.message);}
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
  try {
    state.referenceAnalysis = await api(`/api/references/${state.activeReference.id}/analyze`, {method:"POST"});
    if (state.localNlp?.enabled) await api(`/api/references/${state.activeReference.id}/nlp`, {method:"POST"});
    renderReferenceDetail();
    toast(state.referenceAnalysis.cached ? "已加载本地分析缓存" : "本地分析完成");
  } catch(error) { toast(error.message); }
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
  const file = $("#reference-file").files[0];
  const url = $("#reference-url").value.trim();
  const extension = file?.name.split(".").pop().toLowerCase();
  const text = file && extension === "txt" ? await file.text() : $("#reference-text").value;
  const title = $("#reference-title").value.trim() || file?.name.replace(/\.(txt|docx|pdf)$/i, "") || url;
  const metadata={platform:$("#reference-platform").value||null,content_type:$("#reference-content-type").value||null,project_id:$("#reference-project").value||null};
  if (!file && !url && !text.trim()) return toast("请选择文档、输入网址或粘贴正文");
  try {
    let source;
    if (url) source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:"url",source_uri:url,...metadata})});
    else if (file && extension !== "txt") source = await api("/api/references/import", {method:"POST", body:JSON.stringify({title,source_type:extension,source_uri:file.name,data_base64:await fileBase64(file),...metadata})});
    else source = await api("/api/references", {method:"POST", body:JSON.stringify({title, text, source_type:file ? "txt" : "paste",...metadata})});
    event.target.reset(); state.activeReference = source; state.referenceContent = ""; state.referenceAnalysis = null;
    await loadAll(); toast("参考资料已导入");
  } catch(error) { toast(error.message); }
});
const fileBase64 = file => new Promise((resolve,reject) => { const reader=new FileReader(); reader.onload=()=>resolve(String(reader.result).split(",")[1]); reader.onerror=reject; reader.readAsDataURL(file); });
["reference-search","reference-filter-platform","reference-filter-type","reference-filter-project"].forEach(id=>$("#"+id)?.addEventListener(id==="reference-search"?"input":"change",renderReferences));

async function learnReference() {
  if (!state.activeReference) return;
  try { const result=await api(`/api/references/${state.activeReference.id}/learn`,{method:"POST"}); state.mechanisms=await api("/api/learning/mechanisms"); renderLearning(); toast(`已提炼 ${result.mechanisms.length} 个带证据机制`); }
  catch(error) { toast(error.message); }
}
async function modelLearnReference() { if(!state.activeReference||!confirm("模型深度分析会调用已配置 API，并可能产生费用。继续？"))return; try{toast("模型正在分窗分析...");const result=await api(`/api/references/${state.activeReference.id}/model-learn`,{method:"POST"});state.mechanisms=await api("/api/learning/mechanisms");renderLearning();toast(`深度分析完成，得到 ${result.mechanisms.length} 个候选机制`);}catch(error){toast(error.message);} }

async function loadProjectLearning() {
  const projectId=$("#learning-project").value;
  state.projectLearning=projectId ? await api(`/api/projects/${projectId}/learning`) : null;
  renderLearningArtifacts();
}

function renderLearning() {
  const select=$("#learning-project"); if (!select) return;
  select.innerHTML=state.projects.length ? state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("") : '<option value="">请先创建作品</option>';
  if (state.activeProject) select.value=state.activeProject.id;
  const adopted=new Set((state.projectLearning?.adoptions||[]).map(item=>item.node_id));
  $("#learning-mechanisms").innerHTML=state.mechanisms.length ? state.mechanisms.map(item=>{const needsConfirm=Number(item.data.confidence||0)<0.7&&item.status!=="confirmed";return `<article class="mechanism-item"><h3>${escapeHtml(item.data.name)}</h3><p><strong>位置：</strong>${escapeHtml(item.data.structural_position||"未标注")} · <strong>置信度：</strong>${Math.round(Number(item.data.confidence||0)*100)}%</p><p><strong>观察事实：</strong>${escapeHtml(item.data.fact)}</p><p><strong>分析解释：</strong>${escapeHtml(item.data.interpretation)}</p><p><strong>迁移方法：</strong>${escapeHtml(item.data.transfer_guidance)}</p><p><strong>不适用：</strong>${escapeHtml((item.data.incompatible_conditions||[]).join("；"))}</p>${item.evidence?.[0]?`<blockquote class="mechanism-evidence">${escapeHtml(item.evidence[0].excerpt)}</blockquote>`:""}<div class="mechanism-actions"><button class="secondary" data-mechanism-confirm="${item.id}">${item.status==="confirmed"?"已确认":"确认分析"}</button><button class="primary" data-mechanism-adopt="${item.id}" ${(adopted.has(item.id)||needsConfirm)?"disabled":""} title="${needsConfirm?"低置信度候选需先确认":""}">${adopted.has(item.id)?"已采纳":"采纳到作品"}</button><button class="secondary" data-mechanism-reject="${item.id}">拒绝</button></div></article>`;}).join("") : '<p class="skill-meta">分析参考资料后，这里会展示带证据的可迁移机制</p>';
  document.querySelectorAll("[data-mechanism-confirm]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismConfirm,"confirm")));
  document.querySelectorAll("[data-mechanism-adopt]").forEach(button=>button.addEventListener("click",()=>adoptMechanism(button.dataset.mechanismAdopt)));
  document.querySelectorAll("[data-mechanism-reject]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismReject,"reject")));
  if (select.value && !state.projectLearning) loadProjectLearning(); else renderLearningArtifacts();
}
async function reviseMechanism(id,action) { try { await api(`/api/learning/nodes/${id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})}); state.mechanisms=await api("/api/learning/mechanisms"); renderLearning(); toast(action==="confirm"?"分析已确认":"分析已拒绝"); } catch(error){toast(error.message);} }
async function adoptMechanism(id) { const projectId=$("#learning-project").value; if(!projectId)return toast("请先选择作品"); try { await api(`/api/projects/${projectId}/learning/adoptions/${id}`,{method:"POST",body:JSON.stringify({edits:{}})}); await loadProjectLearning(); renderLearning(); toast("已采纳并生成新版创作蓝图"); } catch(error){toast(error.message);} }
function renderLearningArtifacts(){ const shell=$("#learning-artifacts"); if(!shell)return; const artifacts=state.projectLearning?.artifacts||[]; shell.innerHTML=artifacts.length?artifacts.map(item=>`<details class="learning-artifact" open><summary><strong>${escapeHtml(learningArtifactLabels[item.artifact_type]||item.artifact_type)}</strong><span>版本 ${item.version} · ${item.status==="stale"?"待复核":"生效中"}</span></summary><div class="project-learning-copy">${readableLearningValue(item.data)}</div></details>`).join(""):'<p class="skill-meta">采纳机制或建立文笔资料后在此显示</p>'; }
$("#learning-project").addEventListener("change",async event=>{ state.activeProject=state.projects.find(item=>item.id===event.target.value)||state.activeProject; state.projectLearning=null; await loadProjectLearning(); renderLearning(); });
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
    const originality=result.analysis?.originality||{}; const nlp=result.analysis?.nlp||{};
    shell.innerHTML = `<div class="candidate-metrics"><div><strong>${report.naturalness_score}</strong><span>自然度</span></div><div><strong>${report.blocking_count}</strong><span>阻断问题</span></div><div><strong>${report.targeted_count}</strong><span>局部优化项</span></div><div><strong>${Number(result.effective_words).toLocaleString()}</strong><span>正文有效字数 · 纯汉字 ${Number(result.han_characters).toLocaleString()} · 总字符 ${Number(result.characters).toLocaleString()}</span></div></div><p class="skill-meta">全文扫描 ${escapeHtml(result.analysis_status)} · LTP ${nlp.available?"已完成":"规则降级"} · 原创检查仅限本地语料（${escapeHtml(result.review_scope||"local_corpus_only")}） · 连续片段 ${Number(originality.continuous_passages?.length||0)} · 人名 ${Number(originality.similar_names?.length||0)} · 语义候选 ${Number(originality.semantic_candidates?.length||0)}</p>${report.findings.length ? `<div class="candidate-findings">${report.findings.slice(0,5).map(item => `<p><strong>${escapeHtml(item.code)}</strong><span>第 ${item.segment} 段 · ${escapeHtml(item.excerpt)}</span></p>`).join("")}</div>` : '<p class="skill-meta">本地扫描未发现明显模板化问题</p>'}`;
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
  $("#wizard-back").disabled = state.wizardStep === 0; $("#wizard-next").hidden = state.wizardStep === steps.length - 1; $("#wizard-analyze").hidden = state.wizardStep !== steps.length - 1; $("#wizard-confirm").hidden = state.wizardStep !== steps.length - 1;
  document.querySelectorAll("[data-wizard-step]").forEach(button => button.addEventListener("click", async () => { await saveWizardStep(); state.wizardStep = Number(button.dataset.wizardStep); renderWizard(); }));
  let timer; document.querySelectorAll(".field-value,.field-policy").forEach(control => control.addEventListener("input", () => { $("#wizard-save-state").textContent = "保存中"; clearTimeout(timer); timer=setTimeout(() => saveWizardStep().catch(error => toast(error.message)),500); }));
  renderWizardSummary();
  if (state.interviewWizardId === wizard.id) renderInterview(); else loadInterview().catch(error => toast(error.message));
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
  $("#run-context").innerHTML=(stages.join("") || '<p class="skill-meta">本次运行尚无已完成阶段</p>') + quality + (tools.length ? `<div class="context-tools"><strong>工具调用收据</strong><span>${tools.length} 条 · ${escapeHtml([...new Set(tools.map(item => item.execution_mode))].join("、"))}</span></div>` : "");
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
