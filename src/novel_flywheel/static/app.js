const state = { projects: [], trash: [], providers: [], skills: [], wizards: [], references: [], mechanisms: [], styleCandidates:[], selectedReferenceIds:new Set(), referenceSelectionBusy:false, referenceSelectionStatus:null, referenceSelectionPendingIds:[], referenceSelectionPendingTitles:[], projectLearning:null, effectiveRules:null, outlines:null, activeOutlineCandidateId:null, outlineComparison:null, learningReport:null, attractionMap:null, referenceTask:null, referenceTaskTimer:null, localNlp:null, workflowAnalysis:null, market:null, marketBaselines:[], marketBaseline:null, marketMatch:null, importReceipt:null, publicationPreview:null, candidateQuality:null, candidateControls:null, candidateLoadState:"missing", workbenchManuscript:null, workbenchOutline:null, workbenchRuns:[], workbenchRunsLoadState:"loading", workbenchGeneration:0, workbenchTask:null, runStartingProjectId:null, activeRunProjectId:null, runMonitorGeneration:0, revisionRun:null, revisionReport:null, revisionPollTimer:null, revisionRefreshGeneration:0, revisionFinalizing:false, revisionIssues:[], activeReference: null, referenceContent: "", referenceAnalysis: null, activeProject: null, activeWizard: null, wizardStep: 0, wizardConfirmedMethods:null, wizardMethodsFor:null, selectedWizardMethods:new Set(), wizardSourceReferenceId:null, wizardAutoOutline:false, activeRun: null, pollTimer: null, interviewWizardId: null, interviewMessages: [], interviewBusy: false, editingProviderId: null, storyState: null, materials: null, activeCharacter: null, activeMaterialGroup:"characters", activeMaterialPath:null };
const creatableReferenceTypes = new Set(["reference_work", "popular_sample"]);
const referenceCreationUnavailable = "这类资料只用于查阅，不能直接创建作品";
const WIZARD_METHOD_LIMIT = 12;
const VIEW_GROUPS = {
  workbench:"creation", projects:"creation",
  materials:"learning", learning:"learning",
  market:"market",
  models:"settings", skills:"settings", trash:"settings"
};
const desktopOpenViewGroups = new Set(["creation"]);
let mobileOpenViewGroup = "creation";
const mobileNavigation = window.matchMedia("(max-width: 800px)");
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
const toolRequiredRoles = new Set(["planning"]);
const workflowLabels = {
  "initialize-skills":"作品初始化", "short-story":"短篇完整创作", "long-setup":"长篇准备",
  "long-chapter":"长篇章节创作", "materials-audit":"资料检查", "materials-repair":"资料修复",
  "short-revision":"安全定向返修", archive:"归档", primary:"主模型", circuit_fallback:"备用模型"
};
const findingLabels = {
  timestamp_scene_fragment:"时间与场景切换过于模板化", epiphany_formula:"顿悟表达过于公式化",
  binary_formula:"“不是……而是……”句式重复", vague_metaphor:"比喻含义不够具体",
  emotion_explained:"直接解释情绪", weak_adverb_density:"弱化副词偏多",
  theme_summary_ending:"结尾概括主题过多", one_sentence_paragraph_run:"连续单句成段",
  uniform_short_sentence_run:"连续短句过于整齐", dialogue_ping_pong:"连续对话缺少动作和变化",
  production_text:"正文混入修改说明", checklist_judgment:"连续下结论，缺少过程",
  mixed_script_corruption:"正文出现异常中英文混字", duplicate_paragraph:"正文出现重复段落",
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
  token_budget_exhausted:"模型用量已到上限", "story-init":"作品基础资料",
  "character-management":"人物资料", worldbuilding:"世界设定", "plot-structure":"剧情结构",
  "initialize-skills":"准备人物与设定"
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
    "Server disconnected without sending a response.":"模型服务断开连接，没有返回内容；已有进度已保留。",
    "Final review providers failed; preserved the best candidate":"终审模型和备用模型都没有完成检查，当前最佳候选稿已保留，可以检查模型设置后重试。",
    "Final review incomplete; preserved best candidate":"终审没有完成，当前最佳候选稿已保留，可以检查模型设置后重试。",
    "Editorial quality gate did not pass within the correction limit":"已达到返工次数上限，稿件仍未通过质量检查，当前最佳候选稿已保留。",
    "Editorial quality gate requires a full pass; preserved conditional candidate":"当前候选稿达到条件通过，但还不能设为正式稿；候选稿已保留。",
    "Program restarted while task was active":"程序重启时任务尚未完成，任务已暂停；已有结果已保留，可以继续运行。",
    "[Errno 22] Invalid argument":"系统写入文件时遇到路径或文件名问题（错误码 22），候选稿已保留，请检查文件名后重试。",
    "Review primary and configured fallback did not produce usable output":"审稿模型和备用模型都没有返回可用结果，已有内容已保留。",
    "终审模型返回内容不完整，精简报告恢复也未完成；已保留最佳稿":"终审模型返回内容不完整，精简报告恢复也未完成；最佳稿已保留，可以重新终审。",
    "终审模型已返回，但结果未通过系统校验，已保留最佳稿":"终审模型已返回，但内容不完整，系统没有采用半份报告；最佳稿已保留，可以重新终审。",
    "Skill completed without file proposals":"模型读取了作品资料，但没有生成本阶段需要的文件；已有资料不受影响，再次初始化只会继续未完成阶段。",
    "Controlled runtime ended without required tool output":"模型读取了作品资料，但自动补救后仍未生成本阶段需要的文件；已有资料不受影响，再次初始化只会继续未完成阶段。",
    "Model exceeded the eight-round tool limit":"模型多次读取资料后仍未完成写入；已有资料不受影响，再次初始化只会继续未完成阶段。"
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
    .replace(/\btool_use\b/g,"工具调用")
    .replace(/\bstory-init\b/g,"作品基础资料")
    .replace(/\bcharacter-management\b/g,"人物资料")
    .replace(/\bworldbuilding\b/g,"世界设定")
    .replace(/\bplot-structure\b/g,"剧情结构");
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
  cancelled:"已终止", failed:"失败", waiting_confirmation:"等待你确认",
  waiting_local_fix:"需要人工处理", interrupted:"意外中断，可继续"
}[run.status] || "状态待确认");
const isActiveRunStatus = status => ["queued","running","cancelling"].includes(status);

function deriveWorkbenchTaskState(snapshot) {
  const runs=snapshot.runs||[];
  const activeRun=runs.find(item=>["queued","running","cancelling"].includes(item.status));
  const latestRevision=runs.find(item=>item.workflow==="short-revision");
  const resumableRevision=latestRevision&&snapshot.revisionRun?.id===latestRevision.id&&["failed","cancelled","interrupted"].includes(latestRevision.status);
  const issues=(snapshot.issues||[]).filter(item=>!["resolved","closed","preserved"].includes(item.status));
  const visibleIssues=issues.slice(0,3);
  if(!snapshot.project)return {stage:"准备开始新作品",issues:[],action:{kind:"references",label:"从样本开始"},detail:"可以先选择爆款样本或参考作品；也可以直接点击上方“开始新作品”。"};
  if(snapshot.runStarting)return {stage:"正在启动任务",issues:visibleIssues,action:{kind:"starting",label:"正在启动"},detail:"请求已经发出，请不要重复点击。",showProgress:true};
  if(snapshot.runsLoadState==="loading")return {stage:"正在读取作品状态",issues:[],action:{kind:"loading",label:"正在读取"},detail:"读取完成后会自动显示下一步。"};
  if(snapshot.runsLoadState==="error")return {stage:"暂时没有读到任务状态",issues:visibleIssues,action:{kind:"reload",label:"重新读取状态"},detail:"没有启动任何新任务，请重新读取当前作品。",showProgress:true};
  if(!snapshot.hasFormalOutline&&!activeRun)return {stage:"等待你选择正式大纲",issues:visibleIssues,action:{kind:"outline",label:"选择大纲"},detail:"候选大纲不会自动用于创作；确认正式大纲后，才能准备人物、设定和正文。"};
  if(!snapshot.initialized&&!activeRun)return {stage:"作品还没有准备好",issues:visibleIssues,action:{kind:"initialize",label:"继续初始化"},detail:"完成初始化后，系统才能按这部作品的要求写作。"};
  if(activeRun)return {stage:`正在处理：${runLabel(activeRun.current_stage||activeRun.workflow)}`,issues:visibleIssues,action:{kind:"progress",label:"查看当前进度"},detail:"当前任务仍在进行，不会重复启动。",showProgress:true};
  if(resumableRevision)return {stage:"上次返修没有完成",issues:visibleIssues,action:{kind:"resume-revision",label:"从失败项继续"},detail:"已完成的修改仍然保留，打开返修区后再确认继续。",showProgress:true};
  if(snapshot.project?.mode==="short"&&snapshot.candidateLoadState==="missing")return {stage:"还没有正文",issues:[],action:{kind:"generate-short",label:"生成完整短篇"},detail:"将使用当前大纲、设定和写作要求生成候选稿。"};
  if(snapshot.revisionRun?.status==="waiting_confirmation")return {stage:"修改已经准备好，等你确认",issues:visibleIssues,action:{kind:"confirm-revision",label:"继续确认修改"},detail:"请比较修改前后，再决定采用或保留原写法。"};
  const hasBlockingIssues=Number(snapshot.blockingCount||0)>0||issues.some(item=>item.mandatory||["critical","blocking"].includes(item.severity));
  if(hasBlockingIssues||snapshot.revisionRun?.status==="waiting_local_fix"){
    const action=issues.length?{kind:"repair",label:"查看并选择问题"}:{kind:"local-scan",label:"查看本地扫描"};
    return {stage:`有 ${issues.length||Number(snapshot.blockingCount||0)} 个问题需要处理`,issues:visibleIssues,action,detail:"先处理必须解决的问题，再继续终审或投稿。"};
  }
  if(snapshot.canSetFormal&&!snapshot.formalMatchesCandidate)return {stage:"候选稿已经通过检查",issues:visibleIssues,action:{kind:"formal",label:"设为正式稿"},detail:"确认后才会替换当前正式稿。"};
  if(snapshot.publicationPreview?.ready)return {stage:"正式稿可以准备投稿",issues:visibleIssues,action:{kind:"publication",label:"准备投稿"},detail:"填写标题、卖点和简介后再生成投稿包。"};
  if(snapshot.project?.mode==="long"&&snapshot.candidateLoadState==="missing")return {stage:"可以继续长篇创作",issues:visibleIssues,action:{kind:"long-writing",label:"继续长篇创作"},detail:"打开创作区，选择准备全书或生成下一章。"};
  if(snapshot.candidateLoadState==="loading")return {stage:"正在读取稿件状态",issues:[],action:{kind:"quality",label:"查看稿件质量"},detail:"读取完成后会自动更新下一步。"};
  if(snapshot.candidateLoadState==="error")return {stage:"暂时没有读到稿件状态",issues:[],action:{kind:"reload",label:"重新读取状态"},detail:"没有启动任何新任务，请重新读取当前作品。"};
  return {stage:"稿件状态已更新",issues:visibleIssues,action:{kind:"quality",label:"查看稿件质量"},detail:"打开质量区查看完整检查结果和建议。"};
}
function workbenchFormalMatchesCandidate(candidate,publicationPreview,manuscript) {
  if(!candidate?.available)return false;
  const candidateHash=candidate.quality_summary?.manuscript_state?.manuscript_hash;
  if(publicationPreview?.manuscript_hash&&candidateHash)return publicationPreview.manuscript_hash===candidateHash;
  return manuscript?.source==="formal"&&String(manuscript.content||"").trim()===String(candidate.content||"").trim();
}
function currentWorkbenchSnapshot() {
  const runs=state.workbenchRuns||[];
  const initialization=runs.find(item=>item.workflow==="initialize-skills");
  const summary=state.candidateQuality?.quality_summary||{};
  return {
    project:state.activeProject,
    hasFormalOutline:Boolean(state.workbenchOutline?.current?.exists),
    initialized:initialization?.status==="completed",
    runs,
    runsLoadState:state.workbenchRunsLoadState,
    runStarting:state.runStartingProjectId===state.activeProject?.id,
    issues:summary.issues||[],
    blockingCount:state.candidateQuality?.diagnostics?.blocking_count||0,
    candidateLoadState:state.candidateLoadState,
    canSetFormal:Boolean(summary.publication_authority?.can_set_formal),
    formalMatchesCandidate:workbenchFormalMatchesCandidate(state.candidateQuality,state.publicationPreview,state.workbenchManuscript),
    publicationPreview:state.publicationPreview,
    revisionRun:state.revisionRun?.projectId===state.activeProject?.id?state.revisionRun:null,
  };
}
function renderWorkbenchTaskState(snapshot=currentWorkbenchSnapshot()) {
  const task=deriveWorkbenchTaskState(snapshot);
  state.workbenchTask=task;
  const project=snapshot.project;
  $("#workbench-current-project").innerHTML=project
    ? `<strong>${escapeHtml(project.title)}</strong><span>${project.mode==="short"?"短篇":"长篇"} · ${Number(project.target_words||0).toLocaleString()} 字</span>`
    : "<strong>现在没有正在写的作品</strong><span>学习库和市场分析仍然可以正常使用</span>";
  $("#workbench-current-stage").innerHTML=`<strong>${escapeHtml(task.stage)}</strong><span>${escapeHtml(task.detail)}</span>`;
  $("#workbench-priority-issues").innerHTML=task.issues.length
    ? `<h3>现在最需要处理</h3>${task.issues.map(item=>`<article><strong>${escapeHtml(revisionSafeText(item.title,"正文问题"))}</strong><p>${escapeHtml(revisionSafeText(item.effect,"这处问题可能影响阅读或理解。"))}</p><span>${escapeHtml(qualityIssueStatus(item.status))}</span></article>`).join("")}`
    : '<p class="workbench-no-issues">当前没有需要优先展示的问题。</p>';
  const action=$("#workbench-primary-action");
  action.textContent=task.action.label;
  action.dataset.workbenchAction=task.action.kind;
  action.disabled=["starting","loading"].includes(task.action.kind);
  const latest=(snapshot.runs||[])[0];
  $("#workbench-task-progress").hidden=!(task.showProgress||latest&&["failed","cancelled","interrupted"].includes(latest.status));
}
function openWorkbenchDetails(selector) {
  const details=$("#workbench-details");
  details.open=true;
  const target=$(selector)||details;
  if(!target.matches("button,input,select,textarea,summary,a,[tabindex]"))target.tabIndex=-1;
  target.focus?.({preventScroll:true});
  target.scrollIntoView({behavior:"smooth",block:"start"});
}
function openWorkbenchLocalScan() {
  $("#workbench-details").open=true;
  const localScan=$("#candidate-quality .quality-drawer");
  if(localScan)localScan.open=true;
  openWorkbenchDetails(localScan?"#candidate-quality .quality-drawer":".candidate-band");
}
$("#workbench-primary-action").addEventListener("click",async event=>{
  const action=event.currentTarget.dataset.workbenchAction;
  if(action==="new")return navigateToView("projects");
  if(action==="references"){await navigateToView("learning");return switchLearningView("references");}
  if(action==="outline")return openProjectOutlineGenerator(state.activeProject.id);
  if(action==="reload")return renderActiveProject();
  if(action==="initialize")return $("#initialize-project").click();
  if(action==="generate-short")return $("#run-short").click();
  if(action==="formal")return $("#publish-candidate").click();
  if(action==="progress")return $("#workbench-task-progress").scrollIntoView({behavior:"smooth",block:"center"});
  if(action==="publication")return openWorkbenchDetails(".publication-band");
  if(action==="long-writing")return openWorkbenchDetails(".action-panel");
  if(action==="resume-revision"){
    const projectId=state.activeProject?.id;
    openWorkbenchDetails("#quality-revision-workspace");
    await resumeTargetedRevision();
    if(state.activeProject?.id===projectId)await renderActiveProject();
    return;
  }
  if(action==="confirm-revision")return openWorkbenchDetails("#revision-group-results");
  if(action==="repair")return openWorkbenchDetails("#quality-revision-workspace");
  if(action==="local-scan")return openWorkbenchLocalScan();
  openWorkbenchDetails(".candidate-band");
});

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const error = new Error(typeof body.detail === "string" ? body.detail : (body.detail?.message || body.detail?.code || `HTTP ${response.status}`));
    error.code = body.detail?.code || "";
    throw error;
  }
  if (response.status === 204) return null;
  return response.json();
}
function toast(message) { const el = $("#toast"); el.textContent = message; el.classList.add("show"); setTimeout(() => el.classList.remove("show"), 2600); }

function syncNavigationGroups() {
  document.querySelectorAll(".sidebar .nav-group").forEach(group => {
    const name=group.dataset.navGroup;
    const expanded=mobileNavigation.matches
      ? name===mobileOpenViewGroup
      : desktopOpenViewGroups.has(name);
    group.classList.toggle("expanded",expanded);
    group.querySelector(".nav-group-toggle").setAttribute("aria-expanded",String(expanded));
    group.querySelector(".nav-group-items").hidden=!expanded;
  });
}
function showView(name, label) {
  const groupName=VIEW_GROUPS[name];
  const nav=document.querySelector(`.sidebar .nav-item[data-view="${name}"]`);
  const view=document.getElementById(name);
  if(!groupName||!nav||!view?.classList.contains("view"))return false;
  mobileOpenViewGroup=groupName;
  desktopOpenViewGroups.add(groupName);
  syncNavigationGroups();
  document.querySelectorAll(".sidebar .nav-item").forEach(item=>{
    item.classList.remove("active");
    item.removeAttribute("aria-current");
  });
  document.querySelectorAll(".sidebar .nav-group").forEach(group=>group.classList.remove("active"));
  document.querySelectorAll(".view").forEach(item=>item.classList.remove("active"));
  nav.classList.add("active");
  nav.setAttribute("aria-current","page");
  nav.closest(".nav-group").classList.add("active");
  view.classList.add("active");
  $("#view-title").textContent=label||nav.textContent.trim()||"小说飞轮";
  return true;
}
async function navigateToView(name, label) {
  if(!showView(name,label))return false;
  if(name==="workbench")await renderActiveProject();
  if(name==="materials")await renderMaterials();
  if(name==="market")await loadMarketDashboard();
  return true;
}
document.querySelectorAll(".nav-group-toggle").forEach(button=>button.addEventListener("click",()=>{
  const name=button.closest(".nav-group").dataset.navGroup;
  if(mobileNavigation.matches)mobileOpenViewGroup=button.getAttribute("aria-expanded")==="true"?null:name;
  else if(desktopOpenViewGroups.has(name))desktopOpenViewGroups.delete(name);
  else desktopOpenViewGroups.add(name);
  syncNavigationGroups();
}));
mobileNavigation.addEventListener("change",()=>{
  mobileOpenViewGroup=VIEW_GROUPS[document.querySelector(".sidebar .nav-item.active")?.dataset.view]||"creation";
  syncNavigationGroups();
});
document.querySelectorAll(".nav-item").forEach(button=>button.addEventListener("click",()=>{
  navigateToView(button.dataset.view,button.textContent.trim()).catch(()=>toast("页面数据读取失败，请稍后重试。"));
}));
document.querySelectorAll("[data-view-target]").forEach(button=>button.addEventListener("click",()=>{
  navigateToView(button.dataset.viewTarget).catch(()=>toast("页面数据读取失败，请稍后重试。"));
}));
syncNavigationGroups();

async function loadReferences() {
  const references=await api("/api/references");
  const existingIds=new Set(references.map(item=>item.id));
  let selectionChanged=false;
  for(const id of state.selectedReferenceIds)if(!existingIds.has(id)){state.selectedReferenceIds.delete(id);selectionChanged=true;}
  if(selectionChanged){state.referenceSelectionStatus=null;state.referenceSelectionPendingIds=[];state.referenceSelectionPendingTitles=[];}
  state.references=references;
  return references;
}

async function loadAll() {
  [state.projects, state.trash, state.providers, state.skills, state.wizards, state.references, state.mechanisms, state.styleCandidates, state.localNlp, state.marketBaselines] = await Promise.all([api("/api/projects"), api("/api/projects/trash"), api("/api/providers"), api("/api/skills"), api("/api/wizards"), loadReferences(), api("/api/learning/mechanisms?view=all"), api("/api/learning/style-candidates?view=all"), api("/api/settings/local-nlp"), api("/api/market/baselines")]);
  renderProjects(); renderTrash(); renderProviders(); renderSkills(); renderBindings(); renderWizardDrafts(); renderReferences(); renderLearning(); renderNlpStatus();
}

function renderReferenceSelectionBar() {
  const shell=$("#reference-selection-status"),create=$("#create-from-selected-references"),clear=$("#clear-reference-selection");
  if(!shell||!create||!clear)return;
  const count=state.selectedReferenceIds.size;
  const fallbackTitle=count?`已选择 ${count} 篇资料`:"已选择 0 篇资料";
  const status=state.referenceSelectionStatus;
  shell.className=`reference-selection-status ${status?.kind||""}`.trim();
  shell.innerHTML=`<strong>${escapeHtml(status?.title?`${status.title} · ${fallbackTitle}`:fallbackTitle)}</strong><span>${escapeHtml(status?.detail||"只可选择参考作品和爆款样本；检查和本地提炼不会调用模型。")}</span>`;
  create.textContent="用所选资料创建新作品";
  create.disabled=!count||state.referenceSelectionBusy;
  clear.disabled=!count||state.referenceSelectionBusy;
}

function setReferenceSelectionStatus(kind,title,detail) {
  state.referenceSelectionStatus={kind,title,detail};
  renderReferenceSelectionBar();
}

function clearReferenceReadinessNotice() {
  state.referenceSelectionPendingIds=[];
  state.referenceSelectionPendingTitles=[];
  $("#learning-mechanisms .reference-readiness-notice")?.remove();
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
  renderReferenceSelectionBar();
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
    const selectable=creatableReferenceTypes.has(item.content_type);
    const title=selectable?`选择《${item.title}》用于创建作品`:referenceCreationUnavailable;
    return `<div class="reference-list-item ${item.id === state.activeReference.id ? "active" : ""}"><label class="reference-select-control ${selectable?"":"unsupported"}" title="${escapeHtml(title)}"><input type="checkbox" data-reference-select="${escapeHtml(item.id)}" aria-label="${escapeHtml(title)}" ${state.selectedReferenceIds.has(item.id)?"checked":""} ${selectable&&!state.referenceSelectionBusy?"":"disabled"}></label><button type="button" class="reference-list-open" data-reference-id="${escapeHtml(item.id)}"><strong>${escapeHtml(item.title)}</strong><span>${escapeHtml(platformLabel(item.platform||"未指定平台"))} · ${escapeHtml(typeLabels[item.content_type]||"参考作品")}${linked?` · 关联《${escapeHtml(linked.title)}》`:""}</span><span>${Number(item.latest_version?.character_count || 0).toLocaleString()} 字符 · ${item.versions.length} 个版本</span></button></div>`;
  }).join("") : '<p class="skill-meta reference-empty">没有符合筛选条件的资料</p>';
  list.querySelectorAll("[data-reference-id]").forEach(button => button.addEventListener("click", () => selectReference(button.dataset.referenceId)));
  list.querySelectorAll("[data-reference-select]").forEach(input=>input.addEventListener("change",()=>{
    if(input.checked)state.selectedReferenceIds.add(input.dataset.referenceSelect);
    else state.selectedReferenceIds.delete(input.dataset.referenceSelect);
    state.referenceSelectionStatus=null;
    clearReferenceReadinessNotice();
    renderReferenceSelectionBar();
  }));
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
  const canCreate=creatableReferenceTypes.has(source.content_type);
  const createAction=`<button class="primary" data-reference-create ${canCreate&&!state.referenceSelectionBusy?"":"disabled"} title="${canCreate?"从这篇资料开始创建作品":referenceCreationUnavailable}">${canCreate?"从此资料创建作品":"仅供查阅，不能创建"}</button>`;
  const report = state.referenceAnalysis?.result;
  const metrics = report?.metrics;
  const findings = report?.findings || [];
  const learning=state.learningReport?.source_id===source.id?state.learningReport:null;
  const learningSummary=learning?`<section class="reference-learning-summary"><div><strong>${learning.analyzed_windows} / ${learning.window_count}</strong><span>窗口已扫描</span></div><div><strong>${learning.coverage_percent}%</strong><span>全文覆盖率</span></div><div><strong>${learning.mechanisms.length}</strong><span>合并后候选机制</span></div><p>本地规则已覆盖全文；候选机制的多处证据已合并，可在下方项目学习区查看。</p></section>`:"";
  const diagnosticsHtml=metrics?`<section class="reference-metrics"><div><strong>${metrics.sentence_count}</strong><span>句子</span></div><div><strong>${metrics.paragraph_count}</strong><span>段落</span></div><div><strong>${metrics.average_sentence_length}</strong><span>平均句长</span></div><div><strong>${findings.length}</strong><span>需要你复核</span></div></section><section class="reference-findings"><h3>本地诊断</h3><p class="section-intro">这些是本地规则找到的疑似位置，不代表文章一定有错。请结合原文决定是否修改。</p>${findings.length?findings.map(renderDiagnosticFinding).join(""):'<p class="skill-meta">当前没有发现需要你复核的问题。</p>'}</section>`:'<section><p class="skill-meta">尚未运行本地诊断。点击后会扫描全文，并说明每个疑似问题为什么值得检查。</p></section>';
  $("#reference-detail").innerHTML = `<header><div><p class="eyebrow">${escapeHtml(sourceTypeLabels[source.source_type]||"参考资料")}</p><h2>${escapeHtml(source.title)}</h2><p class="skill-meta">${Number(source.latest_version?.character_count || 0).toLocaleString()} 字符 · 版本 ${source.latest_version?.version || 1}</p></div><div class="reference-actions">${createAction}<button class="secondary" data-reference-analyze>本地诊断</button><button class="secondary" data-reference-learn>本地提炼</button><button class="secondary" data-reference-model-learn>模型全文分析</button><button class="secondary danger-text" data-reference-delete>删除</button></div></header><section class="reference-task-status" data-reference-task-status></section>${learningSummary}${renderLocalAttractionCandidates(learning?.attraction_candidates)}${renderAttractionMap()}${diagnosticsHtml}<details class="reference-source"><summary>查看原文</summary><pre>${escapeHtml(state.referenceContent)}</pre></details>`;
  renderReferenceTaskStatus();
  $("#reference-detail [data-reference-analyze]").addEventListener("click", analyzeReference);
  $("#reference-detail [data-reference-learn]").addEventListener("click", learnReference);
  $("#reference-detail [data-reference-model-learn]").addEventListener("click", modelLearnReference);
  $("#reference-detail [data-reference-create]").addEventListener("click",()=>startWizardFromReference([source.id]));
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
    await loadReferences();
    state.marketMatch=null; renderReferences(); toast("榜单作品关联已确认");
  }catch(error){toast(error.message);}
}

async function unlinkReferenceMarket(referenceId){
  if(!confirm("解除榜单关联？文本正文和资料分类会继续保留。"))return;
  try{
    await api(`/api/market/references/${referenceId}/link`,{method:"DELETE"});
    state.activeReference=await api(`/api/references/${referenceId}`);
    await loadReferences();
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
      [state.mechanisms,state.styleCandidates]=await Promise.all([api("/api/learning/mechanisms?view=all"),api("/api/learning/style-candidates?view=all")]);
      state.attractionMap=task.result?.attraction_map||await api(`/api/references/${sourceId}/attraction-map`);
      const count=task.result?.mechanisms?.length||0,styleCount=task.result?.style_candidates?.length||0;
      task.summary=(count||styleCount)?`全文模型分析完成：剧情写法 ${count} 条，文笔候选 ${styleCount} 条`:"全文模型分析完成；模型未形成有充分证据的候选内容，剧情吸引力报告仍可查看";
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
$("#clear-reference-selection").addEventListener("click",()=>{
  state.selectedReferenceIds.clear();
  state.referenceSelectionStatus=null;
  clearReferenceReadinessNotice();
  renderReferences();
});
$("#create-from-selected-references").addEventListener("click",()=>startWizardFromReference([...state.selectedReferenceIds]));

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
  try{await api("/api/market/refresh",{method:"POST",body:JSON.stringify({source_id:"zhihu-salt"})});await loadMarketDashboard();await loadReferences();renderReferences();toast("榜单快照已保存，本地市场分析已同步更新");}
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
  try { const result=await api(`/api/references/${state.activeReference.id}/learn`,{method:"POST"}); state.learningReport=result; state.mechanisms=await api("/api/learning/mechanisms?view=all");state.referenceTask={...state.referenceTask,status:"completed",phase:"completed",finished_at:new Date().toISOString(),completed_windows:result.analyzed_windows,total_windows:result.window_count,summary:`全文覆盖 ${result.coverage_percent}%，整理出 ${result.mechanisms.length} 个候选写法`}; renderReferenceDetail(); renderLearning(); toast(`全文覆盖 ${result.coverage_percent}% · 已提炼 ${result.mechanisms.length} 个候选机制`); }
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
    const [projectLearning,outlines,effectiveRules]=await Promise.all([
      api(`/api/projects/${projectId}/learning`),
      api(`/api/projects/${projectId}/learning/outlines`),
      api(`/api/projects/${projectId}/learning/effective-rules`),
    ]);
    if($("#learning-project").value!==projectId)return false;
    state.projectLearning=projectLearning;state.outlines=outlines;state.effectiveRules=effectiveRules;
  }else{
    if($("#learning-project").value)return false;
    state.projectLearning=null;state.effectiveRules=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null;
  }
  renderLearningArtifacts();
  renderOutlineWorkspace();
  return true;
}

function setOutlineOperationStatus(kind,title,detail,action=null){
  const shell=$("#outline-operation-status");if(!shell)return;
  shell.className=`outline-operation-status ${kind||""}`.trim();
  shell.innerHTML=`<strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail||"")}</span>`;
  if(action){
    const button=document.createElement("button");button.type="button";button.className="secondary outline-retry-action";button.textContent=action.label;button.addEventListener("click",action.run);shell.append(button);
  }
}

async function loadOutlineWorkspace(){
  const projectId=learningProjectId();
  state.outlines=projectId?await api(`/api/projects/${projectId}/learning/outlines`):null;
  const ids=new Set((state.outlines?.candidates||[]).map(item=>item.id));
  if(!ids.has(state.activeOutlineCandidateId)){state.activeOutlineCandidateId=null;state.outlineComparison=null;}
  renderOutlineWorkspace();
}

function outlineChangeLabel(type){return {added:"新增剧情",removed:"删除剧情",changed:"内容变化",reordered:"位置调整",uncertain:"暂时判断不了"}[type]||"发生变化";}

function outlineMarketReferenceMarkup(check){
  if(!check||check.status==="not_enabled")return "";
  const signals=(check.signals||[]).map(item=>`<p><b>${item.detected?"已出现":"可留意"}</b><span>${escapeHtml(item.message)}</span></p>`).join("");
  const mechanisms=(check.mechanisms||[]).map(item=>`<li><strong>${escapeHtml(item.name)}</strong><span>${Number(item.work_count||0)} 篇样本出现${item.position_median==null?"":` · 常见位置约全文 ${Number(item.position_median)}%`}</span></li>`).join("");
  const details=mechanisms?`<details><summary>查看同类样本中的常见机制</summary><ul>${mechanisms}</ul>${check.boundary?`<small>${escapeHtml(check.boundary)}</small>`:""}</details>`:"";
  return `<section class="outline-market-reference"><header><strong>同类市场参考</strong><span>${escapeHtml(check.message||"市场数据只供参考，不影响候选大纲的应用。")}</span></header>${signals?`<div>${signals}</div>`:""}${details}</section>`;
}

function renderOutlineComparison(report){
  const shell=$("#outline-comparison");if(!shell)return;
  if(!report){shell.hidden=true;shell.innerHTML="";return;}
  shell.hidden=false;
  const summary=report.summary||{},changes=report.changes||[];
  const canonConflicts=report.canon_conflicts||[];
  const risks=(report.risks||[]).map(item=>`<li>${escapeHtml(item)}</li>`).join("");
  const list=changes.length?changes.map(item=>`<article class="outline-change-item">
    <label><input type="checkbox" data-outline-change="${item.id}"> <span><strong>${escapeHtml(item.label)}</strong><small>${outlineChangeLabel(item.type)}</small></span></label>
    <p>${escapeHtml(item.explanation||"请查看前后内容后决定是否采用。")}</p>
    ${item.impact?`<p class="outline-impact"><strong>可能影响：</strong>${escapeHtml(item.impact)}</p>`:""}
    <details><summary>查看改动前后</summary><div class="outline-before-after"><section><span>当前大纲</span><pre>${escapeHtml(item.current_text||"（没有这段）")}</pre></section><section><span>候选大纲</span><pre>${escapeHtml(item.candidate_text||"（将删除这段）")}</pre></section></div></details>
  </article>`).join(""):'<div class="learning-empty"><strong>没有发现变化</strong><p>这个候选与当前大纲内容相同，不需要应用。</p></div>';
  const firstOutline=report.stage==="no_outline";
  const marketReference=outlineMarketReferenceMarkup(report.market_check);
  const canonCards=canonConflicts.length?`<section class="outline-canon-conflicts"><header><strong>先确认这些设定</strong><span>每一项只保留一个答案，确认后才会进入后续写作。</span></header>${canonConflicts.map(item=>`<article class="outline-canon-item"><div><span>${escapeHtml(item.label)}</span><p>${escapeHtml(item.explanation)}</p></div><fieldset><legend>最终采用</legend><label><input type="radio" name="canon-${escapeHtml(item.id)}" data-canon-choice="${escapeHtml(item.id)}" value="keep_current"><span><small>保留项目资料</small><strong>${escapeHtml(item.current_value)}</strong></span></label><label class="${item.can_use_candidate?"":"disabled"}"><input type="radio" name="canon-${escapeHtml(item.id)}" data-canon-choice="${escapeHtml(item.id)}" value="use_candidate" ${item.can_use_candidate?"":"disabled"}><span><small>${item.can_use_candidate?"采用候选大纲":"项目资料已锁定"}</small><strong>${escapeHtml(item.candidate_value)}</strong></span></label></fieldset></article>`).join("")}</section>`:"";
  shell.innerHTML=`<header><div><h4>${firstOutline?"准备建立第一版正式大纲":"比较结果"}</h4><p>${firstOutline?"当前作品还没有正式大纲；整体采用后，这份候选会成为第一版正式大纲。":"勾选你想要的变化；没有勾选的内容会保持原样。"}</p></div><div class="outline-change-summary"><span>新增 <b>${summary.added||0}</b></span><span>删除 <b>${summary.removed||0}</b></span><span>调整 <b>${summary.changed||0}</b></span></div></header>
    ${marketReference}
    ${risks?`<ul class="outline-risks">${risks}</ul>`:""}
    ${canonCards}
    <div class="outline-change-list">${list}</div>
    <footer>
      ${canonConflicts.length?'<button class="secondary" type="button" data-outline-create-project>按这份大纲创建新作品</button>':""}
      ${report.semantic_review_recommended?'<button class="secondary" type="button" data-outline-semantic>请模型判断</button>':""}
      <button class="secondary" type="button" data-outline-apply-selected ${changes.length?"":"disabled"}>应用勾选的变化</button>
      <button class="primary" type="button" data-outline-apply-whole ${!(report.lock_failures||[]).length&&changes.length?"":"disabled"}>${firstOutline?"设为第一版正式大纲":"整体采用这个版本"}</button>
    </footer>`;
  shell.querySelector("[data-outline-semantic]")?.addEventListener("click",semanticReviewOutline);
  shell.querySelector("[data-outline-create-project]")?.addEventListener("click",createProjectFromOutline);
  shell.querySelector("[data-outline-apply-selected]")?.addEventListener("click",()=>applyOutline(false));
  shell.querySelector("[data-outline-apply-whole]")?.addEventListener("click",()=>applyOutline(true));
}

async function createProjectFromOutline(){
  const projectId=learningProjectId(),candidateId=state.activeOutlineCandidateId;
  if(!projectId||!candidateId||!confirm("按这份候选大纲创建一部新作品？原作品、原大纲和运行记录都会保留。"))return;
  setOutlineOperationStatus("busy","正在创建新作品","先建立独立作品和第一版正式大纲，不会修改原作品。");
  try{
    const created=await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}/create-project`,{method:"POST"});
    await refreshProjectsAfterConfirmation(created);
    toast("新作品已创建，下一步可以重新生成人物和设定");
    await navigateToView("workbench");
  }catch(error){setOutlineOperationStatus("error","创建失败",error.message);}
}

async function createProjectFromCurrentOutline(){
  const projectId=learningProjectId();
  if(!projectId||!confirm("按当前正式大纲创建一部新作品？原作品、原资料和运行记录都会保留。"))return;
  setOutlineOperationStatus("busy","正在创建新作品","当前大纲会成为新作品的第一版正式大纲，原作品不会改变。");
  try{
    const created=await api(`/api/projects/${projectId}/learning/outlines/create-project`,{method:"POST"});
    await refreshProjectsAfterConfirmation(created);
    toast("新作品已创建，下一步可以重新生成人物和设定");
    await navigateToView("workbench");
  }catch(error){setOutlineOperationStatus("error","创建失败",error.message);}
}

function renderOutlineWorkspace(){
  const currentShell=$("#outline-current"),candidateShell=$("#outline-candidates"),editor=$("#outline-editor");
  if(!currentShell||!candidateShell||!editor)return;
  const current=state.outlines?.current;
  const readiness=state.outlines?.writing_readiness;
  const currentVersion=Number(current?.outline_version)>0?`第 ${current.outline_version} 版`:"旧项目已有版本";
  const currentConflicts=(readiness?.conflicts||[]).map(item=>`<p><strong>${escapeHtml(item.label)}</strong><span>项目资料：${escapeHtml(item.current_value)} · 正式大纲：${escapeHtml(item.candidate_value)}</span></p>`).join("");
  currentShell.innerHTML=current?.exists
    ?`<strong>当前正式大纲 · ${currentVersion}</strong><span>${escapeHtml(readiness?.message||current.message)}</span>${currentConflicts?`<div class="outline-current-conflicts">${currentConflicts}</div>`:""}${readiness&&!readiness.ready?'<button class="secondary" type="button" data-current-outline-create-project>按当前大纲创建新作品</button><small>新作品重新生成人物和设定；原作品、原资料和运行记录都会保留。</small>':""}`
    :`<strong>还没有正式大纲</strong><span>${escapeHtml(current?.message||"生成候选后，可以把它设为第一版大纲。")}</span>`;
  currentShell.querySelector("[data-current-outline-create-project]")?.addEventListener("click",createProjectFromCurrentOutline);
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
  const canonChoices=Object.fromEntries([...document.querySelectorAll("[data-canon-choice]:checked")].map(item=>[item.dataset.canonChoice,item.value]));
  const canonConflicts=report.canon_conflicts||[];
  if(canonConflicts.some(item=>!canonChoices[item.id]))return setOutlineOperationStatus("error","还有设定没有确认","请在“先确认这些设定”中，为每一项选择最终采用的内容。");
  const manuscript=Boolean(report.current?.manuscript_exists);
  const message=whole?(manuscript?"整体采用会改变后续创作依据，但不会修改已经写好的正文。确认继续？":report.stage==="no_outline"?"把这个候选设为该作品的第一版正式大纲？":"整体采用这个候选版本作为正式大纲？"):`应用勾选的 ${changeIds.length} 项变化？其他内容保持不变。`;
  if(!confirm(message))return;
  setOutlineOperationStatus("busy","正在应用大纲","系统正在保存新版本并检查锁定设定。");
  try{
    await api(`/api/projects/${projectId}/learning/outline-candidates/${candidateId}/apply`,{method:"POST",body:JSON.stringify({expected_revision:report.state_revision,apply_whole:whole,change_ids:whole?null:changeIds,confirm_manuscript_impact:whole&&manuscript,canon_choices:canonChoices})});
    state.activeOutlineCandidateId=null;state.outlineComparison=null;await loadProjectLearning();
    setOutlineOperationStatus("success","正式大纲已确认","人物、设定和正文还不会自动生成。下一步请到工作台确认准备作品。",{label:"前往工作台",run:()=>navigateToView("workbench")});
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

const listValue=value=>Array.isArray(value)?value:(value==null||value===""?[]:[value]);
const styleFieldLabels={viewpoint:"叙事视角",narrative_distance:"叙事距离",sentence_rhythm:"句子节奏",paragraph_rhythm:"段落节奏",dialogue:"对白表达",psychology:"心理描写",action_sensation:"动作与感官",professional_detail:"细节用法",forbidden_patterns:"避免使用"};
const viewpointLabels={first:"第一人称","first-person":"第一人称",second:"第二人称","second-person":"第二人称",third:"第三人称","third-limited":"第三人称限知",third_limited:"第三人称限知","third-person-limited":"第三人称限知","third-omniscient":"第三人称全知",third_omniscient:"第三人称全知","third-person-omniscient":"第三人称全知"};
function readableViewpoint(value){const text=String(value||"").trim();return viewpointLabels[text.toLowerCase()]||(/[a-z]/i.test(text)?"自定义视角":text)||"未指定";}

function styleCandidateApplied(item){
  const baseline=state.projectLearning?.artifacts?.find(value=>value.artifact_type==="prose_baseline")?.data||{};
  return listValue(baseline[item.data.field]).includes(item.data.rule);
}

function renderStyleCandidateCard(item){
  const rejected=item.status==="rejected",confirmed=item.status==="confirmed",applied=styleCandidateApplied(item);
  const evidence=item.evidence||[],hasProject=Boolean(learningProjectId()),field=styleFieldLabels[item.data.field]||"文笔规则";
  const evidenceHtml=evidence.length?`<details class="style-candidate-evidence"><summary>查看原文依据（${evidence.length} 处）</summary>${evidence.slice(0,6).map(value=>`<blockquote class="mechanism-evidence">${escapeHtml(value.excerpt)}</blockquote>`).join("")}</details>`:'<p class="skill-meta">这条候选没有保存可展示的原文依据，不建议采用。</p>';
  const applyAction=hasProject
    ?`<button class="primary" type="button" data-style-apply="${item.id}" ${(!confirmed||applied)?"disabled":""}>${applied?"已加入基础文笔":"加入当前作品"}</button>`
    :(confirmed&&item.source_id?`<button class="primary" type="button" data-style-create-reference="${escapeHtml(item.source_id)}">用这篇资料创建新作品</button>`:'');
  const actions=rejected
    ?`<button class="secondary danger-text" type="button" data-style-delete="${item.id}">永久删除</button>`
    :`<button class="secondary" type="button" data-style-confirm="${item.id}" ${confirmed?"disabled":""}>${confirmed?"分析已确认":"确认这条文笔"}</button>${applyAction}<button class="secondary" type="button" data-style-reject="${item.id}">不采用</button>`;
  return `<article class="style-candidate-item"><header><div><span class="style-candidate-kind">${escapeHtml(field)}</span><h3>${escapeHtml(item.data.rule||"待确认文笔规则")}</h3></div><span class="mechanism-status">${rejected?"已拒绝":confirmed?"已确认":"等待你判断"}</span></header><div class="style-candidate-summary"><span>来自《${escapeHtml(item.source_title||"未记录")}》</span><span>全文证据 ${evidence.length} 处</span></div><div class="style-candidate-use"><section><strong>什么时候适合用</strong><p>${escapeHtml(item.data.when_to_use||"适合在不改变人物和剧情设定的前提下，作为通用表达规则使用。")}</p></section><section><strong>不要怎么用</strong><p>${escapeHtml(item.data.avoid||"不要照搬原句、专名、设定或标志性表达。")}</p></section></div>${evidenceHtml}<p class="style-candidate-note">${rejected?"这条文笔不会进入任何作品。":"确认只表示认可分析；点击“加入当前作品”后，才会生成新的基础文笔版本。已有正文不会改变。"}</p><div class="mechanism-actions">${actions}</div></article>`;
}

function renderMechanismCard(item,adopted,rejectedView){
  const rejected=item.status==="rejected",confirmed=item.status==="confirmed";
  const needsConfirm=Number(item.data.confidence||0)<0.7&&!confirmed;
  const statusLabel=rejected?"已拒绝":confirmed?"已确认":"等待你判断";
  const source=mechanismSourceMeta(item),modelOnly=source.origin==="model";
  const text=(value,fallback)=>modelOnly?readableModelText(value,fallback):String(value||fallback);
  const evidence=item.evidence||[],positions=listValue(item.data.positions);
  const stages=[...new Set(positions.map(mechanismStage))];
  const groups=mechanismEvidenceGroups(item);
  const conditions=text(listValue(item.data.incompatible_conditions).join("；"),"没有明确使用条件，请结合原文证据判断是否适合。 ");
  const modeLabels={short:"短篇",long:"长篇"};
  const modes=listValue(item.data.applicable_modes).map(value=>modeLabels[value]||value);
  const applicableStages=listValue(item.data.applicable_stages);
  const genres=listValue(item.data.applicable_genres);
  const scope=[modes.length?modes.join("、"):"短篇和长篇",applicableStages.length?applicableStages.join("、"):null,genres.length?genres.join("、"):null].filter(Boolean).join(" · ");
  const similar=(item.similar_items||[]).length?`<p class="mechanism-similar">发现意思相近的写法：${item.similar_items.slice(0,2).map(value=>escapeHtml(value.name)).join("、")}。应用前建议只保留表达最清楚的一条。</p>`:"";
  const groupedEvidence=Object.entries(groups).map(([stage,items])=>`<section><strong>${stage} · ${items.length} 处</strong>${items.map(value=>`<blockquote class="mechanism-evidence">${escapeHtml(value.excerpt)}</blockquote>`).join("")}</section>`).join("");
  const deletable=item.deletable!==false;
  const selection=rejectedView&&deletable?`<label class="mechanism-select"><input type="checkbox" data-mechanism-select="${item.id}"> 选择</label>`:"";
  const rejectedActions=deletable?`<button class="secondary danger-text" data-mechanism-delete="${item.id}">永久删除</button>`:`<p class="mechanism-delete-blocked">${escapeHtml(item.delete_reason||"这条写法当前不能删除")}</p><button class="secondary" data-mechanism-release="${item.id}">从作品中移除</button>`;
  const createFirstProject=confirmed&&!state.projects.length&&item.source_id;
  const primaryAction=createFirstProject
    ?`<button class="primary" data-mechanism-create-reference="${escapeHtml(item.source_id)}">用这篇资料创建新作品</button>`
    :`<button class="primary" data-mechanism-adopt="${item.id}" ${(adopted.has(item.id)||needsConfirm)?"disabled":""}>${adopted.has(item.id)?"已应用":"应用到当前作品"}</button>`;
  const activeActions=`<button class="secondary" data-mechanism-confirm="${item.id}" ${confirmed?"disabled":""}>${confirmed?"已保留":"保留为候选"}</button>${primaryAction}<button class="secondary" data-mechanism-reject="${item.id}">不采用</button>`;
  const decision=rejected?"这条写法已被你拒绝。可以永久删除；如果仍在作品中使用，需要先取消应用。":createFirstProject?"当前还没有作品，可以直接用这篇资料开始创建。":"“保留为候选”表示认可分析；“应用到当前作品”会写入创作蓝图，但不会直接修改正文。";
  const modelReason=source.analysis.model?readableModelText(source.analysis.model.reason,"模型完成了复核，但没有提供可读的中文理由。 "):"";
  const localScore=source.analysis.local?.confidence;
  const technical=`<details class="mechanism-judgment-details"><summary>查看判断依据</summary><p>本地判断：${localScore==null?"未运行":`${Math.round(Number(localScore)*100)}%`} · 模型复核：${source.analysis.model?source.detail:"未调用模型"}</p>${modelReason?`<p>模型理由：${escapeHtml(modelReason)}</p>`:""}<p>分析时间：${escapeHtml(formatLocalTimestamp(item.updated_at)||"未记录")}</p></details>`;
  return `<article class="mechanism-item">${selection}<div class="mechanism-source-badges"><span class="${source.tone}">${source.label}</span><span>${source.detail}</span></div><header><div><h3>${escapeHtml(text(item.data.name,"模型提取的候选写法"))}</h3><span class="mechanism-status">${statusLabel}</span></div><div class="mechanism-stage-summary"><strong>来源资料：${escapeHtml(source.analysis.source_title||"未记录")}</strong><span>证据 ${evidence.length||positions.length||1} 处</span><span>适合：${escapeHtml(scope)}</span><span>综合判断：${source.judgment}</span></div></header>${similar}<details class="mechanism-details"><summary>查看详情 · 写法和原文依据</summary><div class="mechanism-explanation"><section><span>它能起什么作用 · 为什么值得学习</span><p>${escapeHtml(text(item.data.interpretation||item.data.emotional_effect,"它可能影响读者对信息、人物或情节推进的感受。"))}</p></section><section><span>什么时候适合使用</span><p>${escapeHtml(scope)}</p></section><section><span>具体怎么使用 · 你的作品可以怎么用</span><p>${escapeHtml(text(item.data.transfer_guidance,"保留这种写法的作用，替换人物、设定、情节和具体表达。"))}</p></section><section><span>什么时候不要用</span><p>${escapeHtml(conditions)}</p></section></div>${evidence[0]?`<section class="mechanism-representative"><span>原文是怎么写的 · 来自《${escapeHtml(source.analysis.source_title||"未记录")}》</span><blockquote class="mechanism-evidence">${escapeHtml(evidence[0].excerpt)}</blockquote></section>`:""}${evidence.length>1?`<details class="mechanism-evidence-list"><summary>查看全部证据（${evidence.length} 处）</summary>${groupedEvidence}</details>`:""}${technical}<p class="mechanism-decision"><strong>${rejected?"当前状态：":"你需要决定："}</strong>${decision}</p></details><div class="mechanism-actions">${rejected?rejectedActions:activeActions}</div></article>`;
}

function renderLearning() {
  const select=$("#learning-project"); if (!select) return;
  const hasProjects=Boolean(state.projects.length);
  select.innerHTML=hasProjects ? state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join("") : '<option value="">暂无作品</option>';
  if (state.activeProject) select.value=state.activeProject.id;
  if(!hasProjects){state.projectLearning=null;state.effectiveRules=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null;}
  $("#learning-application-empty").hidden=hasProjects;
  $("#learning-project-content").hidden=!hasProjects;
  $("#learning-application-title").textContent=hasProjects?"当前作品的创作设置":"开始新作品";
  $("#learning-application-description").textContent=hasProjects?"在这里管理大纲版本、待确认写法和已经生效的规则。所有操作只影响后续创作，不会改动现有正文。":"当前没有作品。先选择参考资料创建，或者直接填写自己的故事设定。";
  const adopted=new Set((state.projectLearning?.adoptions||[]).map(item=>item.node_id));
  const view=mechanismView(),rejectedView=view==="rejected";
  const origin=$("#learning-mechanism-origin")?.value||"all";
  const visible=state.mechanisms.filter(item=>(view==="all"||(rejectedView?item.status==="rejected":item.status!=="rejected"))&&(origin==="all"||(item.data.analysis_origin||"local")===origin));
  const visibleStyles=state.styleCandidates.filter(item=>(view==="all"||(rejectedView?item.status==="rejected":item.status!=="rejected"))&&["all","model"].includes(origin));
  const deletableCount=visible.filter(item=>item.deletable!==false).length;
  const batch=rejectedView&&deletableCount?`<div class="mechanism-batch-actions"><label><input type="checkbox" data-mechanism-select-all> 全选可删除的 ${deletableCount} 条</label><button class="secondary danger-text" data-mechanism-delete-selected>删除所选</button></div>`:"";
  const cards=visible.length?visible.map(item=>renderMechanismCard(item,adopted,rejectedView)).join(""):`<p class="skill-meta">${rejectedView?"当前筛选下没有已拒绝剧情写法":"当前筛选下没有剧情写法候选"}</p>`;
  const styleCards=visibleStyles.length?visibleStyles.map(renderStyleCandidateCard).join(""):'<div class="style-candidate-empty"><strong>还没有文笔候选</strong><p>对参考作品或爆款样本运行“模型全文分析”后，有充分原文证据的文风规则会显示在这里。</p></div>';
  const styleSection=`<section class="style-candidate-section"><header><div><span>文笔</span><h3>从优秀样本学到的表达方式</h3><p>先确认分析，再加入作品。不会照搬原句，也不会自动修改正文。</p></div><strong>${visibleStyles.length} 条</strong></header><div class="style-candidate-list">${styleCards}</div></section>`;
  const mechanismSection=`<section class="mechanism-candidate-section"><header><div><span>剧情</span><h3>情节结构与吸引力写法</h3><p>用于安排开头、推进、反转和结尾，不会改变基础文笔。</p></div><strong>${visible.length} 条</strong></header>${batch}${cards}</section>`;
  const pending=state.referenceSelectionPendingTitles;
  const readiness=pending.length?`<section class="reference-readiness-notice"><strong>还需要确认这些资料的候选写法</strong><ul>${pending.map(title=>`<li>《${escapeHtml(title)}》</li>`).join("")}</ul><p>所选资料会继续保留。确认完成后，可以继续用刚才选择的资料创建作品。</p><button class="primary" type="button" data-reference-selection-retry>重新检查并创建</button></section>`:"";
  $("#learning-mechanisms").innerHTML=readiness+styleSection+mechanismSection;
  document.querySelectorAll("[data-style-confirm]").forEach(button=>button.addEventListener("click",()=>reviseStyleCandidate(button.dataset.styleConfirm,"confirm")));
  document.querySelectorAll("[data-style-reject]").forEach(button=>button.addEventListener("click",()=>reviseStyleCandidate(button.dataset.styleReject,"reject")));
  document.querySelectorAll("[data-style-apply]").forEach(button=>button.addEventListener("click",()=>applyStyleCandidate(button.dataset.styleApply)));
  document.querySelectorAll("[data-style-delete]").forEach(button=>button.addEventListener("click",()=>deleteStyleCandidate(button.dataset.styleDelete)));
  document.querySelectorAll("[data-style-create-reference]").forEach(button=>button.addEventListener("click",()=>startWizardFromReference([button.dataset.styleCreateReference])));
  document.querySelectorAll("[data-mechanism-confirm]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismConfirm,"confirm")));
  document.querySelectorAll("[data-mechanism-adopt]").forEach(button=>button.addEventListener("click",()=>adoptMechanism(button.dataset.mechanismAdopt)));
  document.querySelectorAll("[data-mechanism-create-reference]").forEach(button=>button.addEventListener("click",()=>startWizardFromReference([button.dataset.mechanismCreateReference])));
  document.querySelectorAll("[data-mechanism-reject]").forEach(button=>button.addEventListener("click",()=>reviseMechanism(button.dataset.mechanismReject,"reject")));
  document.querySelectorAll("[data-mechanism-delete]").forEach(button=>button.addEventListener("click",()=>deleteRejectedMechanisms([button.dataset.mechanismDelete])));
  document.querySelectorAll("[data-mechanism-release]").forEach(button=>button.addEventListener("click",()=>releaseMechanism(button.dataset.mechanismRelease)));
  $("[data-mechanism-delete-selected]")?.addEventListener("click",()=>deleteRejectedMechanisms([...document.querySelectorAll("[data-mechanism-select]:checked")].map(item=>item.dataset.mechanismSelect)));
  $("[data-mechanism-select-all]")?.addEventListener("change",event=>document.querySelectorAll("[data-mechanism-select]").forEach(item=>item.checked=event.target.checked));
  $("[data-reference-selection-retry]")?.addEventListener("click",()=>startWizardFromReference([...state.referenceSelectionPendingIds]));
  if (select.value && !state.projectLearning) loadProjectLearning(); else renderLearningArtifacts();
}
$("#learning-empty-reference").addEventListener("click",()=>switchLearningView("references"));
$("#learning-empty-new").addEventListener("click",()=>navigateToView("projects"));
const mechanismView=()=>$("#learning-mechanism-view")?.value||"active";
async function reloadMechanisms(){[state.mechanisms,state.styleCandidates]=await Promise.all([api("/api/learning/mechanisms?view=all"),api("/api/learning/style-candidates?view=all")]);renderLearning();}
async function reviseMechanism(id,action) { try { await api(`/api/learning/nodes/${id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})}); await reloadMechanisms(); toast(action==="confirm"?"分析已确认":"分析已拒绝，可在“已拒绝”中查看"); } catch(error){toast(error.message);} }
async function reviseStyleCandidate(id,action){try{await api(`/api/learning/nodes/${id}/revisions`,{method:"POST",body:JSON.stringify({action,data:{}})});await reloadMechanisms();toast(action==="confirm"?"文笔分析已确认，现在可以加入作品":"文笔候选已拒绝，不会影响任何作品");}catch(error){toast(error.message);}}
async function applyStyleCandidate(id){const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/style-candidates/${id}`,{method:"POST"});await loadProjectLearning();renderLearning();toast("已加入基础文笔并保存新版本；已有正文没有改变");}catch(error){toast(error.message);}}
async function deleteStyleCandidate(id){if(!confirm("永久删除这条已拒绝文笔候选及其原文证据？此操作不可撤销。"))return;try{await api("/api/learning/style-candidates",{method:"DELETE",body:JSON.stringify({node_ids:[id]})});await reloadMechanisms();toast("已删除这条文笔候选");}catch(error){toast(error.message);}}
async function deleteRejectedMechanisms(ids){if(!ids.length)return toast("请先选择要删除的记录");if(!confirm(`永久删除 ${ids.length} 条已拒绝机制及其证据？此操作不可撤销。`))return;try{const result=await api("/api/learning/mechanisms",{method:"DELETE",body:JSON.stringify({node_ids:ids})});await reloadMechanisms();const skipped=result.skipped.length?`；未删除：${result.skipped.map(item=>item.reason).join("；")}`:"";toast(`已删除 ${result.deleted_ids.length} 条${skipped}`);}catch(error){toast(error.message);}}
async function releaseMechanism(id){const item=state.mechanisms.find(value=>value.id===id);const projectIds=item?.active_project_ids||[];if(!projectIds.length)return reloadMechanisms();if(!confirm(`这条写法仍在 ${projectIds.length} 个作品中使用。确认从这些作品的创作蓝图中移除？不会修改已经生成的正文。`))return;try{for(const projectId of projectIds)await api(`/api/projects/${projectId}/learning/rejections/${id}`,{method:"POST",body:JSON.stringify({reason:"用户从已拒绝列表中取消应用"})});state.projectLearning=null;await reloadMechanisms();toast("已从作品中移除，现在可以永久删除");}catch(error){toast(error.message);}}
async function adoptMechanism(id) { const projectId=$("#learning-project").value; if(!projectId)return toast("请先选择作品"); try { await api(`/api/projects/${projectId}/learning/adoptions/${id}`,{method:"POST",body:JSON.stringify({edits:{}})}); await loadProjectLearning(); renderLearning(); toast("已采纳并生成新版创作蓝图"); } catch(error){toast(error.message);} }
function effectiveRulesMarkup(data,compact=false){
  if(!data)return '<p class="skill-meta">尚未读取当前作品的创作设置</p>';
  const layers=(data.layers||[]).map((item,index)=>`<li><b>${index+1}</b><span><strong>${escapeHtml(item.name)}</strong><small>${Number(item.count||0)} 项 · ${escapeHtml(item.status)}</small></span></li>`).join("");
  const conflicts=data.conflicts||[];
  const cautions=data.cautions||[];
  const warnings=conflicts.length?`<div class="effective-rule-warning"><strong>需要你留意 ${conflicts.length} 项</strong>${conflicts.map(item=>`<div class="effective-rule-warning-item"><b>${escapeHtml(item.title||"需要确认的写法")}</b><p>${escapeHtml(item.message)}</p></div>`).join("")}</div>`:'<div class="effective-rule-clear"><strong>没有发现明确冲突</strong><span>生成时会按下方顺序使用。</span></div>';
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
function renderProseBaselineOverview(){
  const overview=state.projectLearning?.prose_baseline||{},defaults=overview.default||{},learned=overview.learned||{};
  const defaultRules=listValue(defaults.rules).map(item=>`<div><span>${escapeHtml(item.label||"默认规则")}</span><p>${escapeHtml(item.rule||"")}</p></div>`).join("");
  const learnedRules=Object.entries(learned).flatMap(([field,values])=>listValue(values).map(rule=>`<div><span>${escapeHtml(styleFieldLabels[field]||"补充规则")}</span><p>${escapeHtml(rule)}</p></div>`)).join("");
  const version=Number(overview.version||0),history=version>1?`<div class="artifact-version-actions"><button class="secondary" type="button" data-artifact-history="prose_baseline">查看和恢复旧版本</button><div data-artifact-history-list="prose_baseline"></div></div>`:"";
  return `<details class="learning-artifact prose-baseline-artifact" open><summary><span><strong>当前基础文笔</strong><small>${version?`系统默认 + 已确认样本文笔 · 版本 ${version}`:"系统默认文笔 · 尚未加入样本规则"}</small></span><b>生效中</b></summary><div class="prose-baseline-overview"><section><h4>作品基础方向</h4><div class="prose-baseline-facts"><span>题材 <b>${escapeHtml(defaults.genre||"未指定")}</b></span><span>视角 <b>${escapeHtml(readableViewpoint(defaults.viewpoint))}</b></span><span>语调 <b>${escapeHtml(defaults.tone||"未指定")}</b></span></div></section><section><h4>系统默认规则</h4><div class="prose-baseline-rules">${defaultRules}</div></section><section><h4>从样本确认并加入的规则</h4><div class="prose-baseline-rules">${learnedRules||'<p class="skill-meta">目前没有。到“候选写法”确认文笔候选后，再加入当前作品。</p>'}</div></section></div>${history}</details>`;
}
function renderLearningArtifacts(){
  const shell=$("#learning-artifacts"); if(!shell)return;
  const artifacts=state.projectLearning?.artifacts||[];
  const reviews=state.projectLearning?.adoption_reviews||[];
  const warning=reviews.length?`<section class="learning-review-alert"><div class="learning-review-list">${reviews.map(renderLearningReview).join("")}</div></section>`:"";
  const otherArtifacts=artifacts.filter(item=>item.artifact_type!=="prose_baseline");
  const content=renderProseBaselineOverview()+(otherArtifacts.length?otherArtifacts.map(renderLearningArtifact).join(""):'');
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
$("#learning-project").addEventListener("change",async event=>{
  const projectId=event.target.value,project=state.projects.find(item=>item.id===projectId);
  if(project&&state.activeProject?.id!==projectId){stopRunMonitor();resetRevisionWorkspace();}
  if(project)state.activeProject=project;
  $("#active-project").value=projectId;
  $("#materials-project").value=projectId;
  state.projectLearning=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null;
  if(await loadProjectLearning())renderLearning();
});
$("#learning-mechanism-view").addEventListener("change",reloadMechanisms);
$("#learning-mechanism-origin").addEventListener("change",renderLearning);
const learningProjectId=()=>$("#learning-project").value;
async function saveLearningArtifact(path,data){const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/${path}`,{method:"PUT",body:JSON.stringify({data})});await loadProjectLearning();toast("已保存为新版本");}catch(error){toast(error.message);}}
$("#baseline-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);await saveLearningArtifact("prose-baseline",{dialogue:form.get("dialogue"),psychology:form.get("psychology"),forbidden_patterns:String(form.get("forbidden")||"").split(/\r?\n/).map(item=>item.trim()).filter(Boolean)});});
$("#voice-form").addEventListener("submit",async event=>{event.preventDefault();const form=new FormData(event.target);const current=state.projectLearning?.artifacts?.find(item=>item.artifact_type==="voice_profiles")?.data||{};await saveLearningArtifact("voice-profiles",{...current,[form.get("name")]:{rules:form.get("profile")}});});
$("#scene-brief-form").addEventListener("submit",async event=>{event.preventDefault();const projectId=learningProjectId();if(!projectId)return toast("请先选择作品");try{await api(`/api/projects/${projectId}/learning/scene-briefs`,{method:"POST",body:JSON.stringify({outline:new FormData(event.target).get("outline")})});await loadProjectLearning();toast("场景简报已生成，可继续编辑");}catch(error){toast(error.message);}});
$("#outline-generate-form").addEventListener("submit",async event=>{
  event.preventDefault();const projectId=learningProjectId();if(!projectId)return setOutlineOperationStatus("error","还没有选择作品","请先在页面顶部选择要处理的作品。");
  const chooseMethods=()=>switchLearningView("mechanisms");
  if(state.projectLearning&&!(state.projectLearning.adoptions||[]).length)return setOutlineOperationStatus("error","还不能生成大纲","请先到“候选写法”确认一条内容，再点“加入当前作品”。",{label:"去选择写法",run:chooseMethods});
  if(!confirm("生成候选会调用规划模型，可能产生费用。结果只进入候选区，不会覆盖正式大纲或正文。继续？"))return;
  const button=event.currentTarget.querySelector("button");button.disabled=true;setOutlineOperationStatus("busy","正在生成候选大纲","规划模型正在整理新版本，完成前请不要重复点击。");
  let created;
  try{created=await api(`/api/projects/${projectId}/learning/generate-outline`,{method:"POST",body:JSON.stringify({brief:new FormData(event.currentTarget).get("brief")})});}
  catch(error){
    const needsMethods=error.code==="outline_generation_not_ready"&&error.message.includes("写法");
    setOutlineOperationStatus("error",needsMethods?"还不能生成大纲":"生成失败",`${error.message} 现有作品、大纲和正文不会改变。`,needsMethods?{label:"去选择写法",run:chooseMethods}:null);button.disabled=false;return;
  }
  state.activeOutlineCandidateId=created?.id||null;
  try{
    await loadOutlineWorkspace();
    if(created?.id&&!(state.outlines?.candidates||[]).some(item=>item.id===created.id))throw new Error("页面暂时没有读到新候选");
    setOutlineOperationStatus("success","候选大纲已生成","全文已经保存在下方；打开后可以编辑、比较，再决定是否应用。");
  }catch(error){
    setOutlineOperationStatus("error","候选已经保存，但页面没有刷新",`${error.message}。不需要重新生成，请重新读取候选列表。`,{label:"重新读取",run:async()=>{try{await loadOutlineWorkspace();setOutlineOperationStatus("success","候选已重新读入","现在可以打开全文，编辑或比较后再决定是否应用。");}catch(retryError){setOutlineOperationStatus("error","仍未读取成功",retryError.message);}}});
  }finally{button.disabled=false;}
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
function workbenchContextMatches(projectId,generation) {
  return (state.activeProject?.id||null)===(projectId||null)&&(generation===undefined||generation===state.workbenchGeneration);
}
function stopRunMonitor() {
  clearTimeout(state.pollTimer);
  state.pollTimer=null;
  state.activeRun=null;
  state.activeRunProjectId=null;
  state.runMonitorGeneration+=1;
  $("#run-cancel").hidden=true;
}
async function loadWorkflowAnalysis(projectId=state.activeProject?.id,generation){
  const shell=$("#workflow-analysis-status"),button=$("#workflow-analysis-toggle");
  if(!projectId){state.workflowAnalysis=null;shell.textContent="请选择作品";button.disabled=true;return;}
  try{
    const result=await api(`/api/projects/${projectId}/learning/workflow-analysis`);
    if(!workbenchContextMatches(projectId,generation))return;
    state.workflowAnalysis=result;
    button.disabled=false;button.textContent=result.enabled?"停用当前作品优化":"为当前作品启用";
    shell.textContent=result.enabled?"已启用 · 首次全文终审，返修后关联窗口复核 · 原创检查仅限本地资料库":"未启用 · 继续使用每轮全文终审";
  }catch{
    if(!workbenchContextMatches(projectId,generation))return;
    state.workflowAnalysis=null;button.disabled=true;shell.textContent="分析流程状态读取失败，请刷新后重试";
  }
}
$("#workflow-analysis-toggle").addEventListener("click",async()=>{
  if(!state.activeProject)return toast("请先选择作品");
  state.workflowAnalysis=await api(`/api/projects/${state.activeProject.id}/learning/workflow-analysis`,{method:"PUT",body:JSON.stringify({enabled:!state.workflowAnalysis?.enabled})});
  await loadWorkflowAnalysis();toast("作品分析流程已更新");
});
function renderProjects(renderActive=true) {
  const select = $("#active-project");
  select.innerHTML = state.projects.length ? state.projects.map(p => `<option value="${p.id}">${escapeHtml(p.title)}</option>`).join("") : '<option value="">没有正在写的作品</option>';
  if (!state.activeProject || !state.projects.some(p => p.id === state.activeProject.id)) state.activeProject = state.projects[0] || null;
  if (state.activeProject) select.value = state.activeProject.id;
  const materialsSelect = $("#materials-project");
  materialsSelect.innerHTML = select.innerHTML;
  if (state.activeProject) materialsSelect.value = state.activeProject.id;
  $("#project-list").innerHTML = state.projects.length ? state.projects.map(p => `<article class="project-item"><h3>${escapeHtml(p.title)}</h3><div class="skill-meta">${p.mode === "short" ? "短篇" : "长篇"} · ${escapeHtml(p.genre)} · ${Number(p.target_words).toLocaleString()} 字</div><div class="project-actions"><button class="secondary" data-continue="${p.id}">继续写作</button><button class="secondary danger-text" data-trash="${p.id}">移入回收站</button></div></article>`).join("") : '<p class="skill-meta">尚无作品</p>';
  document.querySelectorAll("[data-continue]").forEach(button => button.addEventListener("click", () => continueProject(button.dataset.continue)));
  document.querySelectorAll("[data-trash]").forEach(button => button.addEventListener("click", () => trashProject(button.dataset.trash)));
  if(renderActive)renderActiveProject();
}
async function continueProject(projectId) {
  const project = state.projects.find(item => item.id === projectId);
  if (!project) return toast("作品不存在");
  if(state.activeProject?.id!==projectId){stopRunMonitor();resetRevisionWorkspace();}
  state.activeProject = project;
  $("#active-project").value=projectId;
  $("#materials-project").value=projectId;
  await navigateToView("workbench");
  if (project.mode !== "short") return;
  const generation=state.workbenchGeneration;
  let runs;
  try{runs=await api(`/api/projects/${project.id}/runs`);}
  catch{if(workbenchContextMatches(projectId,generation))toast("运行记录读取失败，请重新读取状态。");return;}
  if(!workbenchContextMatches(projectId,generation))return;
  const resumableRun = runs.find(item => item.workflow === "short-story"
    && ["failed","cancelled"].includes(item.status));
  if (!resumableRun) return toast("没有可继续的失败任务");
  await run(`/api/runs/${resumableRun.id}/resume`);
}
async function loadProjectLocations(projectId,generation) {
  const shell = $("#project-locations");
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/locations`);
    if (!workbenchContextMatches(projectId,generation)) return;
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
    if (!workbenchContextMatches(projectId,generation)) return;
    shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`;
  }
}
function qualityScore(value) {
  return Number.isFinite(Number(value)) ? Number(value).toFixed(1).replace(/\.0$/,"") : "待终审";
}
function qualityIssueStatus(value) {
  return ({resolved:"已解决",closed:"已解决",partially_resolved:"部分解决",uncertain:"需要复核",unresolved:"待处理",open:"待处理",preserved:"保留原写法"})[value]||"待处理";
}
function qualitySeverity(value) {
  return ({critical:"必须处理",blocking:"必须处理",major:"优先处理",high:"优先处理",medium:"建议处理",low:"可选优化"})[value]||"建议处理";
}
const revisionPhaseLabels = [
  "正在确认修改位置", "正在修改第N项", "正在检查是否影响其他剧情",
  "正在进行局部复核或全文复核", "已完成、部分完成或需要你确认",
];
const revisionErrorLabels = {
  revision_selection_invalid:"所选问题已经变化，请刷新后重新选择。",
  revision_candidate_changed:"返修候选稿已经变化，请刷新后重试。",
  revision_source_changed:"当前最佳稿已经变化，请重新选择问题。",
  revision_story_state_changed:"作品设定已经变化，请重新开始这次返修。",
  revision_locks_changed:"保护片段已经变化，请重新开始这次返修。",
  revision_run_invalid:"这次返修的记录不可继续，请重新开始。",
  revision_group_not_found:"没有找到这组修改，请刷新页面。",
  revision_group_already_decided:"这组修改已经作出决定，页面即将刷新。",
  revision_group_not_ready:"这组修改还没有通过本地检查。",
  revision_decisions_incomplete:"请先决定每一组内容修改是否采用。",
  revision_gate_failed:"整篇本地检查没有通过，尚未调用终审模型。",
  revision_review_unavailable:"终审暂时不可用，修改决定和当前最佳稿都已保留。",
  revision_not_improved:"这版没有超过当前最佳稿，当前最佳稿继续保留。",
  revision_already_finalized:"这次返修已经完成。",
  run_not_found:"没有找到这次返修记录。",
  project_not_found:"没有找到当前作品。",
  run_not_resumable:"这次返修目前不能继续运行。",
};
const revisionFailureLabels = {
  source_hash_changed:"开始返修后原稿发生了变化，这组修改没有应用。",
  anchor_not_unique:"修改位置在正文中出现多次，系统无法安全确定要改哪一处。",
  mechanical_scope_not_unique:"需要自动修复的位置不够明确，系统没有改动正文。",
  operation_invalid:"这组修改的操作方式未通过本地检查。",
  repair_contract_rejected:"模型给出的修改格式未通过本地检查。",
  model_routes_failed:"首选和备用模型都没有完成这一项。",
  unexpected_group_error:"处理这一项时发生意外，其他已完成结果仍然保留。",
  expansion_contract_rejected:"补写场景的安排未通过本地检查。",
  expansion_draft_rejected:"补写场景未满足约定，系统没有应用。",
};
const revisionReasonLabels = {
  changed_ratio:"改动文字较多", selected_ratio:"需要连带检查的位置较多",
  scene_inserted:"增加了场景", scene_deleted:"删除了场景", scene_moved:"移动了场景",
  scene_merged:"合并了场景", event_order_changed:"事件顺序发生变化",
  scene_order_changed:"场景顺序发生变化", principal_character_changed:"主要人物发生变化",
  key_event_changed:"关键事件发生变化", opening_promise_changed:"开头承诺发生变化",
  climax_changed:"高潮发生变化", ending_changed:"结尾发生变化",
  timeline_changed:"时间线发生变化", causal_relations_changed:"因果关系发生变化",
  seven_step_structure_changed:"七步剧情结构发生变化", principal_goal_changed:"主角目标发生变化",
  key_choice_changed:"关键选择发生变化", life_death_changed:"人物生死状态发生变化",
  identity_changed:"人物身份发生变化", relationship_changed:"人物关系发生变化",
  knowledge_state_changed:"人物知道的信息发生变化", key_evidence_changed:"关键证据发生变化",
  setup_changed:"伏笔发生变化", promise_changed:"故事承诺发生变化",
  question_changed:"显式问题发生变化", payoff_changed:"兑现内容发生变化",
  locked_fact_changed:"锁定事实发生变化", world_rule_changed:"世界规则发生变化",
  protected_passage_changed:"保护片段受到影响", reviewer_requested_full:"复核结果存在不确定之处",
  partially_applied_groups:"有修改没有完整应用", semantic_patch_changed:"内容含义发生变化",
  unverified_mechanical_changes:"自动修复需要再次核对", ltp_unavailable:"语义关联无法在本地确认",
  ambiguous_mapping:"关联位置不够明确", new_blocking_issue:"本地扫描发现新的必须处理问题",
  current_analysis_hash_mismatch:"本地分析与当前正文不一致", stale_analysis:"本地分析需要刷新",
  missing_issue_reconciliation:"有问题尚未逐项复核", invalid_issue_reconciliation:"逐项复核结果不完整",
  unresolved_major_issue:"仍有重要问题没有解决", baseline_manuscript_hash_mismatch:"返修依据的原稿已经变化",
  baseline_analysis_hash_mismatch:"返修依据的本地分析已经变化", empty_incremental_scope:"没有找到足够可靠的局部复核范围",
  unexplained_review_window:"有受影响位置尚未说明原因", incomplete_review_coverage:"关联位置没有全部检查",
};
const revisionGateLabels = {
  source_hash_matches:"返修依据的原稿已经变化",
  analysis_hash_matches:"本地分析与当前候选稿不一致",
  required_text_missing:"需要保留的指定原句缺失",
  forbidden_text_remains:"要求删除的文字仍然存在",
  contract_source_hash_matches:"修改记录与当前原稿不一致",
  patch_groups_complete:"有修改组没有完整应用",
  plan_external_diff_absent:"候选稿出现了计划外改动",
  locked_facts_preserved:"候选稿遗漏了已经锁定的事实",
  passage_protection_missing:"受保护片段缺失",
  passage_protection_mutated:"受保护片段被改动",
  passage_protection_ambiguous:"受保护片段出现多处，无法确定位置",
  analysis_coverage_complete:"本地分析没有覆盖全文",
  local_prose_blockers_clear:"本地扫描仍发现必须处理的文字问题",
  minimum_han_met:"正文有效字数低于当前作品下限",
  maximum_han_not_exceeded:"正文有效字数超过当前作品上限",
};
const revisionCategoryLabel = value => ({story:"剧情",logic:"逻辑",character:"人物",structure:"结构",pacing:"节奏",prose:"文字",style:"表达",production_text:"正文完整性",manuscript_corruption:"正文完整性",canon:"设定",compliance:"投稿要求",length:"篇幅"})[value]||"正文";
const revisionSafeText = (value,fallback) => {
  const text=String(value??"").trim();
  return text&&/[\u3400-\u9fff]/.test(text)&&!/(?:https?:\/\/|[A-Za-z]:\\)/.test(text)?text:fallback;
};
const revisionSafeError = (error,fallback="操作没有完成，请稍后重试。") => revisionErrorLabels[error?.code]||fallback;
const revisionFailureLabel = value => revisionFailureLabels[String(value||"")]||"本地检查没有通过，这组修改没有应用。";
const revisionReasonLabel = value => revisionReasonLabels[String(value||"")]||"改动影响范围需要更完整地复核";
const revisionGateLabel = value => revisionGateLabels[String(value||"")]||"有一项整篇检查没有通过";
const revisionGroupStatusLabel = group => {
  if(group.decision==="adopted")return group.kind==="mechanical"?"已自动修复":"已采用";
  if(group.decision==="rejected")return "已拒绝，保留原写法";
  return ({pending:"等待处理",processing:"正在修改",ready_for_confirmation:"等待你确认",failed:"处理失败",rejected:"未通过本地检查",cancelled:"已停止"})[group.status]||"等待处理";
};
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
function revisionIssueRowMarkup(item) {
  const evidence=Array.isArray(item.evidence)?item.evidence:[];
  const mandatory=Boolean(item.mandatory)||["critical","blocking"].includes(item.severity);
  const actionable=!["resolved","closed","preserved"].includes(item.status);
  const issueId=String(item.issue_id||"");
  const title=revisionSafeText(item.title,"正文问题");
  return `<article class="revision-issue-row ${mandatory?"mandatory":"advisory"}"><div class="revision-issue-choice"><label><input type="checkbox" data-revision-issue="${escapeHtml(issueId)}" ${mandatory&&actionable?"checked":""} ${!actionable||!issueId?"disabled":""}><span><b>${escapeHtml(mandatory?"必须处理":qualitySeverity(item.severity))}</b><strong>${escapeHtml(title)}</strong><small>${escapeHtml(qualityIssueStatus(item.status))} · ${escapeHtml(item.handling_label||"精修模型处理")}</small></span></label><em>会检查 ${evidence.length||1} 处相关位置</em></div><details><summary>查看原因、建议和位置</summary><div><p><strong>从哪里发现</strong>${escapeHtml(item.source_label||"终审发现")}</p><p><strong>谁来处理</strong>${escapeHtml(item.handling_label||"精修模型处理")}</p><p><strong>为什么需要处理</strong>${escapeHtml(revisionSafeText(item.effect,"可能影响理解、可信度或继续阅读的意愿。"))}</p><p><strong>建议怎么改</strong>${escapeHtml(revisionSafeText(item.repair_direction,"结合上下文复核并修改。"))}</p><p><strong>问题类型</strong>${escapeHtml(revisionCategoryLabel(item.category))}</p>${evidence.map(value=>`<blockquote><span>${escapeHtml(revisionSafeText(value.location,"正文相关位置"))}</span>${escapeHtml(revisionSafeText(value.excerpt,"这处原文需要结合上下文复核"))}</blockquote>`).join("")||'<p><strong>出现位置</strong>正文相关位置</p>'}</div></details></article>`;
}
function revisionIssuesMarkup(issues) {
  const actionable=issues.filter(item=>!["resolved","closed","preserved"].includes(item.status));
  if(!actionable.length)return '<div class="quality-empty"><strong>终审没有留下待处理问题</strong><p>仍可展开本地扫描，查看措辞和节奏方面的可选优化。</p></div>';
  const first=actionable.slice(0,3).map(revisionIssueRowMarkup).join("");
  const rest=actionable.slice(3).map(revisionIssueRowMarkup).join("");
  return `<div class="revision-issue-list">${first}</div>${rest?`<details class="revision-more-issues"><summary>查看其余 ${actionable.length-3} 项</summary><div class="revision-issue-list">${rest}</div></details>`:""}<div class="revision-selection-actions"><span data-revision-selection-hint>必须处理项已选中；建议项由你决定。</span><button class="primary" type="button" data-revision-start>修复已选问题（0项）</button></div>`;
}
function revisionWorkspaceEnabled(project=state.activeProject) {
  return project?.mode==="short"&&(project?.optimized_local_review_enabled===true||project?.metadata?.optimized_local_review_enabled===true);
}
function revisionRunBlocksNewRound(run) {
  return Boolean(run&&run.projectId===state.activeProject?.id&&!["completed","waiting_local_fix"].includes(run.status));
}
function revisionContextMatches(projectId,runId,generation) {
  return state.activeProject?.id===projectId&&(!runId||state.revisionRun?.id===runId)&&(generation===undefined||generation===state.revisionRefreshGeneration);
}
function qualityReadOnlyIssuesMarkup(issues) {
  if(!issues.length)return '<div class="quality-empty"><strong>终审没有留下待处理问题</strong><p>仍可展开本地扫描，查看措辞和节奏方面的可选优化。</p></div>';
  const rows=issues.map(item=>`<details class="quality-issue-row"><summary><span><b>${escapeHtml(qualitySeverity(item.severity))}</b><strong>${escapeHtml(revisionSafeText(item.title,"正文问题"))}</strong></span><small>${escapeHtml(qualityIssueStatus(item.status))} · ${escapeHtml(item.handling_label||"精修模型处理")}</small></summary><div><p><strong>从哪里发现</strong>${escapeHtml(item.source_label||"终审发现")}</p><p><strong>谁来处理</strong>${escapeHtml(item.handling_label||"精修模型处理")}</p><p><strong>为什么影响阅读</strong>${escapeHtml(revisionSafeText(item.effect,"可能影响理解、可信度或继续阅读的意愿。"))}</p><p><strong>建议怎么改</strong>${escapeHtml(revisionSafeText(item.repair_direction,"结合上下文复核并修改。"))}</p>${(item.evidence||[]).map(evidence=>`<blockquote><span>${escapeHtml(revisionSafeText(evidence.location,"正文相关位置"))}</span>${escapeHtml(revisionSafeText(evidence.excerpt,"没有保留原文证据"))}</blockquote>`).join("")}</div></details>`);
  return `${rows.slice(0,3).join("")}${rows.length>3?`<details class="revision-more-issues"><summary>查看其余 ${rows.length-3} 项</summary>${rows.slice(3).join("")}</details>`:""}`;
}
function qualityIssuesMarkup(issues) {
  state.revisionIssues=issues;
  return revisionWorkspaceEnabled()?$("#quality-revision-template").innerHTML:qualityReadOnlyIssuesMarkup(issues);
}
function qualityResolvedIssuesMarkup(issues) {
  if(!issues.length)return "";
  const rows=issues.map(item=>`<article class="quality-issue-row resolved"><strong>${escapeHtml(revisionSafeText(item.title,"正文问题"))}</strong><small>${escapeHtml(qualityIssueStatus(item.status))}${item.reconciled_at?` · ${escapeHtml(item.reconciled_at)}`:""}</small><p>${escapeHtml(revisionSafeText(item.reconciliation_evidence,"已按当前稿件完成复核"))}</p></article>`).join("");
  return `<details class="quality-drawer quality-resolved-history"><summary><span><strong>已解决记录</strong><small>${issues.length} 项已退出最需要处理的问题</small></span><b>展开</b></summary><div class="quality-drawer-body">${rows}</div></details>`;
}
function renderRevisionIssueSelection(issues) {
  const workspace=$("#quality-revision-workspace"),shell=$("#revision-issue-selection");
  if(!workspace||!shell||!revisionWorkspaceEnabled())return;
  state.revisionIssues=issues;
  shell.innerHTML=revisionIssuesMarkup(issues);
  workspace.hidden=!(issues.length||state.revisionRun);
  shell.querySelectorAll("[data-revision-issue]").forEach(box=>box.addEventListener("change",updateRevisionSelectionCount));
  shell.querySelector("[data-revision-start]")?.addEventListener("click",startTargetedRevision);
  updateRevisionSelectionCount();
}
function updateRevisionSelectionCount() {
  const shell=$("#revision-issue-selection");if(!shell)return;
  const selected=[...shell.querySelectorAll("[data-revision-issue]:checked")];
  const button=shell.querySelector("[data-revision-start]");
  const openRun=revisionRunBlocksNewRound(state.revisionRun);
  if(button){button.textContent=`修复已选问题（${selected.length}项）`;button.disabled=!selected.length||openRun;}
  const hint=shell.querySelector("[data-revision-selection-hint]");
  if(hint)hint.textContent=openRun?"当前返修结束或继续完成后，才能开始新一轮。":selected.length?`已选择 ${selected.length} 项，只会处理这些问题。`:"至少选择一项；未选建议会保留原写法。";
}
function setRevisionOperationStatus(kind,title,detail,phase=1,settled=false) {
  const shell=$("#revision-operation-status");if(!shell)return;
  shell.className=`operation-status revision-operation-status ${kind}`;
  const success=kind==="success"&&settled;
  const settledKind=kind==="error"?"failed":"waiting";
  const progressKind=success?"complete":settled?settledKind:"";
  const groupCount=Math.max(1,state.revisionReport?.groups?.filter(item=>["ready_for_confirmation","failed","rejected"].includes(item.status)).length||1);
  const progress=revisionPhaseLabels.map((label,index)=>{
    const step=index+1,status=step<phase||success&&step===phase?"done":step===phase?"active":"";
    return `<li class="${status}"><span>${step}</span><b>${escapeHtml(label.replace("N",String(groupCount)))}</b></li>`;
  }).join("");
  shell.innerHTML=`<div class="revision-status-copy"><strong>${escapeHtml(title)}</strong><span>${escapeHtml(detail)}</span></div><ol class="revision-progress ${settled?"settled":""} ${progressKind}">${progress}</ol>`;
}
function revisionPhase(detail,report) {
  if(["completed","waiting_confirmation","waiting_local_fix","failed","cancelled","interrupted"].includes(detail.status))return 5;
  if(["final_review","revision_finalize"].includes(detail.current_stage))return 4;
  if(detail.current_stage==="revision_gate")return 3;
  if(detail.status==="queued"||detail.current_stage==="starting")return 1;
  return 2;
}
function revisionPositionLabel(item) {
  if(!item||typeof item!=="object")return "关联位置";
  if(item.label)return revisionSafeText(item.label,"关联位置");
  if(Number.isInteger(item.paragraph))return `第 ${item.paragraph} 段`;
  if(Number.isInteger(item.sentence))return `第 ${item.sentence} 句`;
  return "关联位置";
}
function revisionGroupMarkup(group,candidateHash) {
  const issue=group.issue||{},decision=group.decision;
  const title=revisionSafeText(issue.title,"正文问题");
  const kindLabel=group.kind==="mechanical"?"自动修复":group.kind==="expansion"?"补充场景":"内容修改";
  const ready=["semantic","expansion"].includes(group.kind)&&group.status==="ready_for_confirmation"&&!decision&&/^[0-9a-f]{64}$/.test(String(candidateHash||""));
  const failures=(group.failures||[]).map(item=>`<li>${escapeHtml(revisionFailureLabel(item.code))}</li>`).join("");
  const positions=(group.related_positions||[]).map(item=>`<li>${escapeHtml(revisionPositionLabel(item))}</li>`).join("");
  const checks=group.local_checks?.passed===true?"已通过整篇本地检查":"本地检查没有通过";
  const actions=ready?`<div class="revision-group-actions"><button class="primary" type="button" data-revision-adopt="${escapeHtml(group.group_id)}">采用这组修改</button><button class="secondary" type="button" data-revision-reject="${escapeHtml(group.group_id)}">拒绝这组修改</button><span>拒绝后会保留原写法，问题仍会留在待处理清单。</span></div>`:decision==="rejected"?'<p class="revision-decision rejected">已拒绝这组修改，保留原写法。</p>':decision==="adopted"?`<p class="revision-decision adopted">${group.kind==="mechanical"?"已自动采用这项机械修复。":"已采用这组修改。"}</p>`:"";
  return `<details class="revision-group ${escapeHtml(group.status||"pending")}"><summary><span><b>${kindLabel}</b><strong>${escapeHtml(title)}</strong></span><small>${escapeHtml(revisionGroupStatusLabel(group))}</small></summary><div class="revision-group-body"><p class="revision-solved"><strong>解决的问题</strong>${escapeHtml(revisionSafeText(issue.impact||issue.suggestion,"按终审要求处理这处正文问题。"))}</p><div class="revision-comparison"><section><span>修改前</span><p>${escapeHtml(revisionSafeText(group.before,"没有可展示的原文片段"))}</p></section><section><span>修改后</span><p>${escapeHtml(revisionSafeText(group.after,"没有生成可用修改"))}</p></section></div><details class="revision-check-details"><summary>查看检查详情</summary><div><p><strong>本地检查</strong>${checks}</p>${positions?`<div><strong>同时检查的关联位置</strong><ul>${positions}</ul></div>`:'<p><strong>关联位置</strong>没有发现需要额外核对的位置</p>'}${failures?`<div><strong>未通过原因</strong><ul>${failures}</ul></div>`:""}</div></details>${actions}</div></details>`;
}
function revisionReviewMarkup(report) {
  const reasons=Array.isArray(report.full_review_reasons)?report.full_review_reasons:[];
  if(report.review_mode==="full"||report.review_mode==="full_fallback"||reasons.length)return `<div class="revision-review-plan full"><strong>需要全文复核</strong><span>${escapeHtml(reasons.map(revisionReasonLabel).join("；")||"改动影响故事整体，系统会重新阅读全文。")}</span></div>`;
  if(report.review_mode==="incremental")return '<div class="revision-review-plan incremental"><strong>只复核改动及关联位置</strong><span>整篇本地检查已通过，且没有发现会改变整体剧情的高风险改动。</span></div>';
  return '<div class="revision-review-plan"><strong>终审方式待确定</strong><span>确认修改后，系统会根据实际影响决定局部复核还是全文复核。</span></div>';
}
function revisionGateMarkup(report) {
  const blocking=Array.isArray(report.gate?.blocking)?report.gate.blocking:[];
  if(!blocking.length)return "";
  const reasons=[...new Set(blocking.map(item=>revisionGateLabel(item?.code)))];
  return `<section class="revision-gate-blockers"><strong>整篇检查发现 ${reasons.length} 项需要先处理</strong><ul>${reasons.map(reason=>`<li>${escapeHtml(reason)}</li>`).join("")}</ul></section>`;
}
function revisionActionsMarkup(detail,report) {
  if(detail.status==="waiting_local_fix")return '<div class="revision-next-actions local-fix"><button class="secondary" type="button" data-revision-return>返回问题清单</button><span>这次任务不能直接续跑。请按上面的清单人工处理正文；重新终审后，再选择仍需返修的问题。</span></div>';
  if(["failed","cancelled","interrupted"].includes(detail.status))return '<div class="revision-next-actions"><button class="primary" type="button" data-revision-resume>继续这次返修</button><span>可以从失败的问题继续，已完成结果不会重做。</span></div>';
  if(detail.status!=="waiting_confirmation")return "";
  const groups=report.groups||[];
  const blocked=groups.some(item=>["failed","rejected","cancelled"].includes(item.status)&&!item.decision);
  const undecided=groups.some(item=>["semantic","expansion"].includes(item.kind)&&item.status==="ready_for_confirmation"&&!item.decision);
  if(blocked)return '<div class="revision-next-actions local-fix"><button class="secondary" type="button" data-revision-return>返回问题清单</button><span>有修改没有通过本地检查，当前最佳稿已保留。请按问题清单人工处理后重新终审。</span></div>';
  if(undecided)return '<p class="revision-next-note">逐组查看修改前后，全部决定后才能开始终审。</p>';
  const button=state.revisionFinalizing?'<button class="primary" type="button" data-revision-finalize disabled>正在检查已确认的修改…</button>':'<button class="primary" type="button" data-revision-finalize>检查已确认的修改</button>';
  return `<div class="revision-next-actions">${button}<span>终审通过后才会成为新的受保护最佳稿，正式稿不会自动替换。</span></div>`;
}
function renderRevisionWorkspace(detail,report) {
  const workspace=$("#quality-revision-workspace"),results=$("#revision-group-results");
  if(!workspace||!results)return;
  state.revisionRun={...detail,projectId:detail.project_id||state.activeProject?.id};state.revisionReport=report;
  workspace.hidden=false;
  const phase=revisionPhase(detail,report),complete=detail.status==="completed";
  const active=["queued","running","cancelling"].includes(detail.status);
  const failed=["failed","cancelled","interrupted"].includes(detail.status);
  const title=complete?"返修已经完成":detail.status==="waiting_confirmation"?"修改建议已生成，需要你确认":detail.status==="waiting_local_fix"?"本地检查没有通过":failed?"本次返修没有完成":phase===1?"正在确认修改位置":phase===2?`正在修改第 ${Math.max(1,(report.groups||[]).filter(item=>["ready_for_confirmation","failed","rejected"].includes(item.status)).length+1)} 项`:phase===3?"正在检查是否影响其他剧情":"正在进行局部复核或全文复核";
  const detailText=complete?"返修结果已通过检查，正式稿仍需由你单独确认。":detail.status==="waiting_confirmation"?"请逐组查看修改前后，再决定采用或拒绝。":detail.status==="waiting_local_fix"?"已保留当前最佳稿。请先查看没有通过的项目。":failed?"已保留当前最佳稿，可以从失败的问题继续。":active?"页面会自动更新进度，请保持当前页面打开。":"已保留当前最佳稿。";
  setRevisionOperationStatus(complete?"success":failed?"error":active?"busy":"warning",title,detailText,phase,phase===5);
  const groups=Array.isArray(report.groups)?report.groups:[];
  results.innerHTML=`${revisionReviewMarkup(report)}${revisionGateMarkup(report)}<div class="revision-groups">${groups.length?groups.map(item=>revisionGroupMarkup(item,report.candidate_hash)).join(""):'<p class="skill-meta">正在准备修改内容，暂时还没有可确认的结果。</p>'}</div>${revisionActionsMarkup(detail,report)}`;
  results.querySelectorAll("[data-revision-adopt]").forEach(button=>button.addEventListener("click",()=>decideRevisionGroup(button.dataset.revisionAdopt,"adopt")));
  results.querySelectorAll("[data-revision-reject]").forEach(button=>button.addEventListener("click",()=>decideRevisionGroup(button.dataset.revisionReject,"reject")));
  results.querySelector("[data-revision-resume]")?.addEventListener("click",resumeTargetedRevision);
  results.querySelector("[data-revision-finalize]")?.addEventListener("click",finalizeTargetedRevision);
  results.querySelector("[data-revision-return]")?.addEventListener("click",()=>$("#revision-issue-selection")?.scrollIntoView({behavior:"smooth",block:"start"}));
  $("#revision-issue-selection")?.querySelectorAll("input,button").forEach(control=>control.disabled=revisionRunBlocksNewRound(state.revisionRun)||state.revisionFinalizing);
  updateRevisionSelectionCount();
  if(workbenchContextMatches(state.revisionRun.projectId)){state.workbenchRuns=[detail,...state.workbenchRuns.filter(item=>item.id!==detail.id)];renderWorkbenchTaskState();}
}
async function startTargetedRevision() {
  const projectId=state.activeProject?.id;
  if(!projectId||!revisionWorkspaceEnabled())return;
  const requestGeneration=state.revisionRefreshGeneration;
  const issue_ids=[...$("#revision-issue-selection").querySelectorAll("[data-revision-issue]:checked")].map(item=>item.dataset.revisionIssue);
  if(!issue_ids.length)return setRevisionOperationStatus("error","还没有选择问题","至少选择一项后再开始。",1,true);
  const button=$("#revision-issue-selection").querySelector("[data-revision-start]");if(button)button.disabled=true;
  setRevisionOperationStatus("busy","正在确认修改位置","只会处理你勾选的问题，当前最佳稿不会被覆盖。",1,false);
  try{
    const run=await api(`/api/projects/${projectId}/revisions`,{method:"POST",body:JSON.stringify({issue_ids})});
    if(!revisionContextMatches(projectId,null,requestGeneration))return;
    state.revisionRun={...run,projectId};state.revisionReport={groups:[]};
    const generation=++state.revisionRefreshGeneration;
    await refreshRevisionRun(run.id,true,projectId,generation);
  }catch(error){if(!revisionContextMatches(projectId,null,requestGeneration))return;setRevisionOperationStatus("error","返修没有开始",revisionSafeError(error,"系统暂时没有开始返修，请稍后重试。"),1,true);updateRevisionSelectionCount();}
}
async function refreshRevisionRun(runId,schedule=true,projectId=state.revisionRun?.projectId,generation=state.revisionRefreshGeneration) {
  if(!runId||!projectId||!revisionContextMatches(projectId,runId,generation))return;
  clearTimeout(state.revisionPollTimer);
  try{
    const detail=await api(`/api/runs/${runId}`);
    if(detail.project_id!==projectId||!revisionContextMatches(projectId,runId,generation))return;
    const report=await api(`/api/runs/${runId}/revision`);
    if(!revisionContextMatches(projectId,runId,generation))return;
    renderRevisionWorkspace(detail,report);
    if(schedule&&["queued","running","cancelling"].includes(detail.status))state.revisionPollTimer=setTimeout(()=>refreshRevisionRun(runId,true,projectId,generation),900);
  }catch(error){if(!revisionContextMatches(projectId,runId,generation))return;setRevisionOperationStatus("error","返修状态读取失败",revisionSafeError(error,"暂时无法读取返修进度，请刷新页面。"),5,true);}
}
async function decideRevisionGroup(groupId,decision) {
  const runId=state.revisionRun?.id,projectId=state.activeProject?.id,candidate_hash=state.revisionReport?.candidate_hash;
  if(!runId||!projectId||!revisionContextMatches(projectId,runId)||!/^[0-9a-f]{64}$/.test(String(candidate_hash||"")))return;
  setRevisionOperationStatus("busy",decision==="adopt"?"正在采用这组修改":"正在拒绝这组修改","正在保存你的决定，正文和最佳稿暂时不会改变。",5,false);
  try{
    await api(`/api/runs/${runId}/revision/groups/${encodeURIComponent(groupId)}/${decision}`,{method:"POST",body:JSON.stringify({candidate_hash})});
    if(!revisionContextMatches(projectId,runId))return;
    await refreshRevisionRun(runId,false,projectId);
  }catch(error){if(!revisionContextMatches(projectId,runId))return;await refreshRevisionRun(runId,false,projectId);if(!revisionContextMatches(projectId,runId))return;setRevisionOperationStatus("error","决定没有保存",revisionSafeError(error,"这组修改暂时无法确认，请刷新后重试。"),5,true);}
}
async function resumeTargetedRevision() {
  const runId=state.revisionRun?.id,projectId=state.activeProject?.id;if(!runId||!projectId||!revisionContextMatches(projectId,runId))return;
  setRevisionOperationStatus("busy","正在继续这次返修","会从第一个失败的问题继续，已完成结果不会重做。",2,false);
  try{await api(`/api/runs/${runId}/resume`,{method:"POST"});if(!revisionContextMatches(projectId,runId))return;await refreshRevisionRun(runId,true,projectId);}
  catch(error){if(!revisionContextMatches(projectId,runId))return;setRevisionOperationStatus("error","没有继续运行",revisionSafeError(error,"这次返修暂时不能继续，请刷新页面。"),5,true);}
}
async function finalizeTargetedRevision() {
  const runId=state.revisionRun?.id,projectId=state.activeProject?.id;if(!runId||!projectId||!revisionContextMatches(projectId,runId))return;
  if(state.revisionFinalizing)return;
  const mode=state.revisionReport?.review_mode;
  const generation=++state.revisionRefreshGeneration;
  state.revisionFinalizing=true;
  const button=$("#revision-group-results")?.querySelector("[data-revision-finalize]");if(button){button.disabled=true;button.textContent="正在检查已确认的修改…";}
  setRevisionOperationStatus("busy","正在进行局部复核或全文复核",mode==="full"?"本次改动可能影响整体剧情，正在重新阅读全文。":"正在复核改动位置、相邻位置和关联剧情。",4,false);
  state.revisionPollTimer=setTimeout(()=>refreshRevisionRun(runId,true,projectId,generation),900);
  try{
    const report=await api(`/api/runs/${runId}/revision/finalize`,{method:"POST"});
    if(!revisionContextMatches(projectId,runId,generation))return;
    clearTimeout(state.revisionPollTimer);
    const detail=await api(`/api/runs/${runId}`);
    if(!revisionContextMatches(projectId,runId,generation))return;
    await loadCandidateQuality(projectId);
    if(!revisionContextMatches(projectId,runId,generation))return;
    state.revisionRefreshGeneration+=1;
    state.revisionFinalizing=false;
    renderRevisionWorkspace(detail,report);
  }catch(error){
    if(!revisionContextMatches(projectId,runId,generation))return;
    clearTimeout(state.revisionPollTimer);
    await refreshRevisionRun(runId,false,projectId,generation);
    if(!revisionContextMatches(projectId,runId,generation))return;
    state.revisionRefreshGeneration+=1;
    if(state.revisionRun?.status==="completed"){state.revisionFinalizing=false;renderRevisionWorkspace(state.revisionRun,state.revisionReport);return;}
    setRevisionOperationStatus("error","终审没有完成",`${revisionSafeError(error,"终审暂时不可用，请稍后重试。")} 已保留当前最佳稿和你的修改决定。`,5,true);
  }finally{
    if(revisionContextMatches(projectId,runId)){state.revisionFinalizing=false;const button=$("#revision-group-results")?.querySelector("[data-revision-finalize]");if(button){button.disabled=false;button.textContent="检查已确认的修改";}}
  }
}
function resetRevisionWorkspace() {
  clearTimeout(state.revisionPollTimer);
  state.revisionRefreshGeneration+=1;
  state.revisionRun=null;state.revisionReport=null;state.revisionFinalizing=false;state.revisionIssues=[];
}
async function loadLatestRevisionWorkspace(projectId,runs,workbenchGeneration) {
  if(!workbenchContextMatches(projectId,workbenchGeneration))return;
  clearTimeout(state.revisionPollTimer);
  const generation=++state.revisionRefreshGeneration;
  const project=state.projects.find(item=>item.id===projectId)||state.activeProject;
  if(!revisionWorkspaceEnabled(project)){resetRevisionWorkspace();return;}
  const latest=(runs||[]).find(item=>item.workflow==="short-revision");
  if(!latest){state.revisionRun=null;state.revisionReport=null;state.revisionFinalizing=false;renderRevisionIssueSelection(state.revisionIssues);return;}
  state.revisionRun={...latest,projectId};
  await refreshRevisionRun(latest.id,true,projectId,generation);
  if(!workbenchContextMatches(projectId,workbenchGeneration))return;
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
  const resolvedIssues=summary.resolved_issues||[];
  const report=result.diagnostics||{findings:[]};
  const originality=result.analysis?.originality||{},nlp=result.analysis?.nlp||{},ledger=result.analysis?.narrative_ledger||{};
  const unresolved=[...(ledger.promises||[]),...(ledger.questions||[]),...(ledger.setups||[])].filter(item=>item.status==="unresolved");
  const wordMaximum=Number(word.maximum||1),wordPercent=Math.max(0,Math.min(100,Math.round(Number(word.current||0)/wordMaximum*100)));
  const localFindings=(report.findings||[]).slice(0,8).map(item=>`<p><strong>${escapeHtml(findingLabel(item.code))}</strong><span>第 ${item.segment} 段 · ${escapeHtml(item.excerpt)}</span></p>`).join("");
  shell.innerHTML=`<div class="candidate-quality-workspace"><header class="quality-workspace-head"><div><span class="quality-state ${summary.manuscript_state?.protected_best?"protected":""}">${stateLabel}</span><h3>${escapeHtml(summary.profile?.label||"稿件质量")}</h3><p class="quality-judge">终审模型：${escapeHtml(summary.profile?.judge_label||"旧记录未保存模型名称")}</p><p>${escapeHtml(score.comparison_message||"等待建立可比较的评分记录")}</p></div><div class="quality-next-action"><span>下一步</span><strong>${escapeHtml(summary.next_action||"继续检查候选稿")}</strong></div></header><div class="quality-score-strip"><div><span>总分</span><strong>${qualityScore(score.current)}</strong></div><div><span>阅读吸引力</span><strong>${qualityScore(dimensions.commercial)}</strong></div><div><span>故事质量</span><strong>${qualityScore(dimensions.story)}</strong></div><div><span>文字表达</span><strong>${qualityScore(dimensions.prose)}</strong></div></div><section class="quality-word-count"><div><strong>正文有效字数 ${Number(word.current||result.han_characters||0).toLocaleString()} 字</strong><span>目标 ${Number(word.minimum||0).toLocaleString()}～${Number(word.maximum||0).toLocaleString()} 个有效正文汉字</span></div><div class="quality-word-track" aria-label="正文篇幅进度"><span style="width:${wordPercent}%"></span></div></section>${authority.can_set_formal?'<div class="quality-ready"><strong>当前稿件已具备设为正式稿的条件</strong><span>按钮已启用，确认后才会替换原正式稿。</span></div>':`<details class="quality-blockers" open><summary>为什么现在不能设为正式稿</summary>${(authority.blocking_reasons||[]).map(reason=>`<p>${escapeHtml(reason)}</p>`).join("")}</details>`}<section class="quality-priority"><header><h3>最需要处理的问题</h3><span>${issues.length?`共 ${issues.length} 项，先显示最重要的 ${Math.min(5,issues.length)} 项`:"没有待处理终审问题"}</span></header>${qualityIssuesMarkup(issues)}</section><details class="quality-drawer"><summary><span><strong>查看本地扫描</strong><small>全文规则、原创候选和叙事账本</small></span><b>展开</b></summary><div class="quality-drawer-body"><div class="quality-local-summary"><span>自然度 <b>${Number(report.naturalness_score||0)}</b></span><span>阻断问题 <b>${Number(report.blocking_count||0)}</b></span><span>局部优化 <b>${Number(report.targeted_count||0)}</b></span><span>语义分析 <b>${nlp.available?"已完成":"标准规则"}</b></span></div>${localFindings?`<div class="candidate-findings">${localFindings}</div>`:'<p class="skill-meta">本地扫描未发现明显模板化问题。</p>'}<p class="skill-meta">原创检查只比较本地资料库：连续片段 ${Number(originality.continuous_passages?.length||0)} 处 · 人名 ${Number(originality.similar_names?.length||0)} 处 · 语义候选 ${Number(originality.semantic_candidates?.length||0)} 处</p><div class="quality-ledger-summary"><strong>叙事账本</strong><span>未兑现 ${unresolved.length} · 已关联 ${(ledger.relations||[]).length} · 场景 ${(ledger.scenes||[]).length}</span>${unresolved.slice(0,8).map(item=>`<p>${escapeHtml(item.kind||"线索")}：${escapeHtml(item.text||"")}</p>`).join("")}</div></div></details><details class="quality-drawer"><summary><span><strong>查看详细评分</strong><small>逐项分数、判断位置和原文依据</small></span><b>展开</b></summary><div class="quality-drawer-body quality-criteria-list">${qualityCriteriaMarkup(score)}</div></details><details class="quality-drawer"><summary><span><strong>评分参考组</strong><small>${(controls.group?.items||[]).length} 份已确认参考</small></span><b>展开</b></summary><div class="quality-drawer-body">${qualityReferencesMarkup(controls)}</div></details><details class="quality-drawer"><summary><span><strong>查看完整正文与保护片段</strong><small>${(controls.protections?.items||[]).filter(item=>item.active).length} 段保护中</small></span><b>展开</b></summary><div class="quality-drawer-body">${passageProtectionsMarkup(controls)}<pre id="candidate-manuscript-preview" class="quality-manuscript-preview" tabindex="0">${escapeHtml(result.content||"")}</pre></div></details></div>`;
  const prioritySection=shell.querySelector(".quality-priority");
  if(prioritySection&&resolvedIssues.length)prioritySection.insertAdjacentHTML("afterend",qualityResolvedIssuesMarkup(resolvedIssues));
  const mandatoryCount=Number(summary.issue_counts?.mandatory||0);
  const totalScore=shell.querySelector(".quality-score-strip > div");
  if(totalScore&&mandatoryCount){const note=document.createElement("small");note.textContent=`${mandatoryCount} 个必须处理问题暂未解决`;totalScore.append(note);}
  const priorityHint=shell.querySelector(".quality-priority > header span");
  if(priorityHint&&issues.length)priorityHint.textContent=`共 ${issues.length} 项，先显示最重要的 ${Math.min(3,issues.length)} 项`;
  bindCandidateQualityActions(result.project_id);
  return authority;
}
function bindCandidateQualityActions(projectId) {
  renderRevisionIssueSelection(state.revisionIssues);
  if(state.revisionReport&&state.revisionRun?.projectId===projectId)renderRevisionWorkspace(state.revisionRun,state.revisionReport);
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
async function loadCandidateQuality(projectId,generation) {
  const shell=$("#candidate-quality"),publish=$("#publish-candidate");
  publish.hidden=true;publish.disabled=true;publish.title="";
  state.candidateQuality=null;state.candidateControls=null;
  state.candidateLoadState=projectId?"loading":"missing";
  if(!projectId){shell.innerHTML='<p class="skill-meta">请先选择作品</p>';setCandidateOperationStatus("","请先选择作品");return;}
  shell.innerHTML='<p class="skill-meta">正在读取候选稿、本地扫描和终审结果…</p>';
  setCandidateOperationStatus("busy","正在读取稿件质量","完成后会显示下一步");
  try{
    const result=await api(`/api/projects/${projectId}/candidate`);
    if(!workbenchContextMatches(projectId,generation))return;
    if(!result.available){state.candidateLoadState="missing";shell.innerHTML='<p class="skill-meta">尚无候选稿。完成正文生成后，这里会显示质量结论和下一步。</p>';setCandidateOperationStatus("","尚无候选稿","先生成或恢复一份正文候选稿");return;}
    const controls=await loadCandidateQualityControls(projectId);
    if(!workbenchContextMatches(projectId,generation))return;
    state.candidateLoadState="available";
    state.candidateQuality=result;state.candidateControls=controls;
    const authority=renderCandidateQualityWorkspace(result,controls);
    const reasons=authority.blocking_reasons||[];
    publish.hidden=state.activeProject?.mode!=="short";
    publish.disabled=!authority.can_set_formal;
    publish.title=authority.can_set_formal?"确认后设为正式稿":reasons.join("；");
    setCandidateOperationStatus(authority.can_set_formal?"success":"warning",result.quality_summary?.next_action||"继续检查候选稿",authority.can_set_formal?"当前稿件已通过全部发布检查":reasons[0]||"等待质量检查");
  }catch(error){if(!workbenchContextMatches(projectId,generation))return;state.candidateLoadState="error";shell.innerHTML=`<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`;setCandidateOperationStatus("error","稿件质量读取失败",error.message);}
}
async function loadWritingRulesSummary(projectId,generation) {
  const shell = $("#writing-rules-summary");
  if (!projectId) { shell.innerHTML = '<p class="skill-meta">请先选择作品</p>'; return; }
  try {
    const result = await api(`/api/projects/${projectId}/learning/effective-rules`);
    if (!workbenchContextMatches(projectId,generation)) return;
    state.effectiveRules=result;shell.innerHTML=effectiveRulesMarkup(result,true);
  } catch(error) { if(!workbenchContextMatches(projectId,generation))return;shell.innerHTML = `<p class="skill-meta error-text">${escapeHtml(error.message)}</p>`; }
}
async function loadPublicationPanel(projectId,generation){
  const panel=$("#platform-profile-panel"),form=$("#zhihu-publication-form"),status=$("#publication-status"),submit=form.querySelector('button[type="submit"]');if(workbenchContextMatches(projectId,generation))state.publicationPreview=null;
  submit.disabled=true;submit.title="请先完成正式稿和终审检查";
  if(!projectId){panel.innerHTML='<p class="skill-meta">请先选择作品</p>';form.hidden=true;return;}
  const project=state.projects.find(item=>item.id===projectId);
  if(project?.mode!=="short"){panel.innerHTML='<p class="skill-meta">知乎盐选短篇创作配置只用于短篇作品，长篇保持原有流程。</p>';form.hidden=true;return;}
  const enabled=project.platform_profile_id==="zhihu-salt-short";
  panel.innerHTML=`<div class="profile-row"><div><strong>${enabled?"已启用知乎盐选短篇创作配置":"尚未指定发布平台"}</strong><p>${enabled?"后续大纲、正文、返修和终审会区分平台要求与市场建议。":"启用后只调整后续创作检查和投稿设置，不会改动现有正文。"}</p></div><button type="button" class="${enabled?"secondary":"primary"}" data-profile-toggle>${enabled?"停用配置":"启用知乎盐选短篇"}</button></div>`;
  panel.querySelector("[data-profile-toggle]").addEventListener("click",()=>changePlatformProfile(enabled?null:"zhihu-salt-short"));form.hidden=!enabled;if(!enabled)return;
  form.elements.title.value ||= project.title||"";form.elements.content_type.value ||= project.genre||"";
  status.className="operation-status busy";status.textContent="正在检查正式稿和终审结果…";
  try{const preview=await api(`/api/projects/${projectId}/publication/zhihu/preview`);if(!workbenchContextMatches(projectId,generation))return;state.publicationPreview=preview;const ready=Boolean(preview.ready);submit.disabled=!ready;submit.title=ready?"生成新的投稿包，旧版本继续保留":`当前还不能生成投稿包：${preview.message}`;status.className=`operation-status ${ready?"success":"warning"}`;status.textContent=`${preview.message} 正文 ${Number(preview.character_count).toLocaleString()} 字。`;}
  catch(error){if(!workbenchContextMatches(projectId,generation))return;submit.disabled=true;submit.title="当前还不能生成投稿包";status.className="operation-status error";status.textContent=`投稿条件检查失败：${error.message}`;}
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
  await navigateToView("learning", "学习库");
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
const materialRoleLabels={protagonist:"主角",counterpart:"重要对手戏人物",deuteragonist:"重要对手戏人物",antagonist:"反派",supporting:"重要配角",minor:"次要人物",narrator:"叙述者"};
const materialStatusLabels={alive:"在世",deceased:"已故",active:"活跃",planned:"计划中"};
function renderMaterialCoverage(groupId) {
  const shell=$("#material-coverage"),coverage=state.materials?.coverage?.[groupId];
  if(!shell)return;
  if(!coverage){shell.innerHTML="";shell.hidden=true;return;}
  const conflicts=groupId==="characters"?(state.materials?.outline_conflicts||[]):[];
  const conflictHtml=conflicts.map(item=>`<p><strong>${escapeHtml(item.label)}</strong><span>项目资料写的是“${escapeHtml(item.current_value)}”，正式大纲写的是“${escapeHtml(item.candidate_value)}”。请先在作品应用页确认最终采用哪一个。</span></p>`).join("");
  const missingHtml=(coverage.missing||[]).length?`<details><summary>查看缺失项和大纲依据</summary><div>${coverage.missing.map(item=>`<p><strong>${escapeHtml(item.name)}</strong><span>${escapeHtml(item.evidence||"正式大纲已明确要求这项资料")}</span></p>`).join("")}</div></details>`:"";
  const review=state.materials?.manifest_review?.status==="model_confirmed"?"规划模型已按大纲原文复核":"本地程序已按大纲明确结构核对";
  shell.hidden=false;shell.className=`material-coverage ${coverage.status==="needs_attention"?"needs-attention":"ready"}`;
  shell.innerHTML=`<header><div><strong>${escapeHtml(coverage.message)}</strong><span>${review}</span></div><span>已有 ${coverage.document_count||0}${coverage.expected_count?` · 大纲明确 ${coverage.expected_count}`:""}</span></header>${conflictHtml}${missingHtml}`;
}
function renderCharacter(profile, document) {
  const shell=$("#character-detail");
  if (!profile) { shell.innerHTML='<p class="skill-meta">暂无人物档案</p>'; return; }
  const facts=[profile.age?`${profile.age} 岁`:"",materialStatusLabels[profile.status]||profile.status||""].filter(Boolean);
  shell.innerHTML=`<header><div><p class="eyebrow">${escapeHtml(materialRoleLabels[profile.role] || "人物")}</p><h2>${escapeHtml(profile.name)}</h2></div><div class="character-facts">${facts.map(item=>`<span>${escapeHtml(item)}</span>`).join("")}</div></header><div class="material-actions"><button class="secondary" data-material-edit>编辑人物档案</button></div><div class="character-tags">${(profile.tags || []).map(tag=>`<span>${escapeHtml(tag)}</span>`).join("")}</div>${profile.arc ? `<section><h3>人物弧线摘要</h3><p>${escapeHtml(profile.arc)}</p></section>` : ""}${(profile.sections || []).map(section=>`<section><h3>${escapeHtml(materialSectionLabels[section.title] || section.title)}</h3><div class="profile-copy">${escapeHtml(section.content)}</div></section>`).join("")}`;
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
  renderMaterialCoverage(state.activeMaterialGroup);
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
    $("#material-coverage").innerHTML=""; $("#material-coverage").hidden=true;
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
    $("#material-tabs").innerHTML=groups.map(group=>{const coverage=result.coverage?.[group.id];const missing=coverage?.missing?.length||0;return `<button class="material-tab ${group.id===state.activeMaterialGroup ? "active" : ""}" data-material-group="${group.id}" role="tab">${escapeHtml(group.label)}<span>${group.documents.length}${missing?` · 缺 ${missing}`:""}</span></button>`;}).join("");
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
  const projectId=state.activeProject.id,requestGeneration=state.workbenchGeneration;
  const button=$("#publish-candidate");
  button.disabled=true;
  setCandidateOperationStatus("busy","正在设为正式稿","正在核对候选稿、终审结果和稿件版本");
  try {
    await api(`/api/projects/${projectId}/candidate/publish`, {method:"POST"});
    if(!workbenchContextMatches(projectId,requestGeneration))return;
    await renderActiveProject();
    if(state.activeProject?.id!==projectId)return;
    setCandidateOperationStatus("success","正式稿已更新","原正式稿已被替换，当前候选稿和终审记录保持绑定");
  } catch(error) {
    if(!workbenchContextMatches(projectId,requestGeneration))return;
    const authority=state.candidateQuality?.quality_summary?.publication_authority;
    button.disabled=!authority?.can_set_formal;
    setCandidateOperationStatus("error","设为正式稿失败",error.message);
  }
});
async function renderActiveProject() {
  const p = state.activeProject;
  const projectId=p?.id||null;
  if(state.activeRunProjectId&&state.activeRunProjectId!==projectId)stopRunMonitor();
  const generation=++state.workbenchGeneration;
  if(!revisionWorkspaceEnabled(p)||state.revisionRun?.projectId&&state.revisionRun.projectId!==projectId)resetRevisionWorkspace();
  $("#short-actions").hidden = !p || p.mode !== "short"; $("#long-actions").hidden = !p || p.mode !== "long";
  $("#project-summary").innerHTML = p ? `<div class="metric"><strong>${escapeHtml(p.title)}</strong><span>当前作品</span></div><div class="metric"><strong>${p.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(p.target_words).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${escapeHtml(p.genre)}</strong><span>题材</span></div>` : '<span>先创建一部作品。</span>';
  $("#trash-project").disabled = !p;
  state.workbenchRuns=[];state.workbenchRunsLoadState="loading";state.workbenchManuscript=null;state.workbenchOutline=null;
  if (!p) {
    stopRunMonitor();state.publicationPreview=null;state.candidateQuality=null;state.candidateLoadState="missing";
    state.workbenchRunsLoadState="available";
    $("#run-list").innerHTML = "";
    await Promise.all([loadProjectLocations(null,generation),loadCandidateQuality(null,generation),loadWritingRulesSummary(null,generation),loadPublicationPanel(null,generation),loadWorkflowAnalysis(null,generation)]);
    if(workbenchContextMatches(null,generation))renderWorkbenchTaskState();
    return;
  }
  $("#workbench-current-project").innerHTML=`<strong>${escapeHtml(p.title)}</strong><span>${p.mode==="short"?"短篇":"长篇"} · ${Number(p.target_words||0).toLocaleString()} 字</span>`;
  $("#workbench-current-stage").innerHTML="<strong>正在读取作品状态</strong><span>很快会显示最需要处理的下一步。</span>";
  $("#workbench-priority-issues").innerHTML='<p class="workbench-no-issues">正在读取问题清单…</p>';
  $("#workbench-primary-action").textContent="正在读取";
  $("#workbench-primary-action").disabled=true;
  const results=await Promise.all([
    loadProjectLocations(projectId,generation),
    loadCandidateQuality(projectId,generation),
    loadWritingRulesSummary(projectId,generation),
    loadPublicationPanel(projectId,generation),
    loadWorkflowAnalysis(projectId,generation),
    api(`/api/projects/${projectId}/manuscript`).catch(()=>null),
    api(`/api/projects/${projectId}/learning/outlines`).catch(()=>null),
  ]);
  if(!workbenchContextMatches(projectId,generation))return;
  state.workbenchManuscript=results[5];
  state.workbenchOutline=results[6];
  let runs;
  try{runs=await api(`/api/projects/${projectId}/runs`);}
  catch{
    if(!workbenchContextMatches(projectId,generation))return;
    state.workbenchRunsLoadState="error";state.workbenchRuns=[];
    $("#run-list").innerHTML='<p class="skill-meta error-text">运行记录读取失败，请重新读取状态。</p>';
    $("#run-state").className="run-state error";$("#run-state").textContent="运行记录读取失败，请重新读取状态。";
    $("#initialize-project").hidden=true;
    ["#run-short","#run-setup","#run-chapter"].forEach(selector=>{$(selector).disabled=true;});
    renderWorkbenchTaskState();
    return;
  }
  if(!workbenchContextMatches(projectId,generation))return;
  state.workbenchRuns=runs;state.workbenchRunsLoadState="available";
  await loadLatestRevisionWorkspace(projectId,runs,generation);
  if(!workbenchContextMatches(projectId,generation))return;
  const initialization = runs.find(run => run.workflow === "initialize-skills");
  const initializing = initialization && ["queued","running","cancelling"].includes(initialization.status);
  const initialized = initialization?.status === "completed";
  const hasFormalOutline=Boolean(state.workbenchOutline?.current?.exists);
  const activeRun = runs.find(run => ["queued","running","cancelling"].includes(run.status));
  const latestRun = runs[0];
  if(!activeRun&&state.activeRunProjectId===projectId)stopRunMonitor();
  $("#initialize-project").hidden = !hasFormalOutline || initialized || initializing;
  ["#run-short", "#run-setup", "#run-chapter"].forEach(selector => { $(selector).disabled = !initialized; });
  $("#run-list").innerHTML = runs.length ? runs.map(r => `<button class="run-row" data-run-detail="${r.id}"><div><strong>${escapeHtml(runLabel(r.workflow))}</strong><div class="skill-meta">${escapeHtml(runLabel(r.current_stage))} · ${escapeHtml(formatLocalTimestamp(r.created_at))}</div></div><span class="status ${isQualityRejected(r) ? "quality-rejected" : r.status}">${escapeHtml(runStatusLabel(r))}</span></button>`).join("") : '<p class="skill-meta">暂无运行记录</p>';
  document.querySelectorAll("[data-run-detail]").forEach(button => button.addEventListener("click", async () => {
    const detail=await api(`/api/runs/${button.dataset.runDetail}`);
    if(workbenchContextMatches(projectId,generation))showRunDetail(detail);
  }));
  renderWorkbenchTaskState();
  if (activeRun) monitorRun(activeRun,projectId,generation);
  else if (latestRun) {
    const detail=await api(`/api/runs/${latestRun.id}`).catch(()=>null);
    if(detail&&workbenchContextMatches(projectId,generation))showRunDetail(detail);
  } else if(workbenchContextMatches(projectId,generation)) {
    $("#run-state").className="run-state error"; $("#run-state").textContent=hasFormalOutline?"作品尚未初始化，请点击“继续初始化”":"请先选择候选大纲并设为正式大纲";
  }
}
$("#active-project").addEventListener("change", event => { stopRunMonitor();resetRevisionWorkspace();state.activeProject = state.projects.find(p => p.id === event.target.value); state.activeCharacter=null; renderProjects(); });
$("#materials-project").addEventListener("change", async event => { stopRunMonitor();resetRevisionWorkspace(); state.activeProject = state.projects.find(p => p.id === event.target.value); state.activeCharacter=null; state.activeMaterialPath=null; $("#active-project").value=event.target.value; await renderMaterials(); });
$("#edit-project-learning").addEventListener("click", async () => {
  if(!state.activeProject)return toast("请先选择作品");
  await navigateToView("learning"); $("#learning-project").value=state.activeProject.id; state.projectLearning=null;
  await loadProjectLearning(); renderLearning();
});

function renderWizardDrafts() {
  const drafts = state.wizards.filter(item => ["draft", "gathering_input", "ready"].includes(item.status) && !item.project_id);
  const select=$("#wizard-drafts"),selected=select.value;
  select.innerHTML = '<option value="">选择草稿</option>' + drafts.map(item => `<option value="${escapeHtml(item.id)}">${escapeHtml(item.answers?.title?.value || (item.mode === "long" ? "未命名长篇" : "未命名短篇"))}</option>`).join("");
  if(drafts.some(item=>item.id===selected))select.value=selected;
  updateWizardDraftControls();
  const learnedSourceIds=new Set(state.mechanisms.map(item=>item.source_id));
  $("#wizard-reference").innerHTML='<option value="">自己构思（原方式）</option>'+state.references.map(item=>creatableReferenceTypes.has(item.content_type)
    ? `<option value="${item.id}">从《${escapeHtml(item.title)}》${learnedSourceIds.has(item.id)?"的学习成果":"开始学习并"}创建</option>`
    : `<option value="${item.id}" disabled>《${escapeHtml(item.title)}》（仅供查阅，不能创建）</option>`).join("");
}
function updateWizardDraftControls(){
  const selected=Boolean($("#wizard-drafts")?.value);
  $("#continue-wizard-draft").disabled=!selected;
  $("#delete-wizard-draft").disabled=!selected;
}
function wizardDraftErrorMessage(error){
  return ({
    wizard_not_found:"草稿不存在或已经删除。当前输入仍然保留，可以刷新后再选。",
    wizard_has_project:"这份开书资料已经创建作品，不能从草稿列表删除。作品和当前输入都没有变化。",
  })[error?.code]||"删除没有完成。当前输入仍然保留，可以重新尝试。";
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
    if(state.wizardSourceReferenceId&&!state.selectedWizardMethods.size&&methods.length<=12)state.selectedWizardMethods=new Set(methods.map(item=>item.id));
    state.wizardConfirmedMethods=methods;renderWizardConfirmedMethods(true);
  }catch{
    if(state.activeWizard?.id!==wizard.id)return;
    $("#wizard-confirmed-method-list").innerHTML='<p class="error-text">读取写法失败，请稍后重试。</p>';
  }
}
function renderWizardConfirmedMethods(show){
  const shell=$("#wizard-confirmed-methods"),list=$("#wizard-confirmed-method-list");if(!shell||!list)return;
  shell.hidden=!show;if(!show||!state.activeWizard)return;
  if(state.wizardMethodsFor!==state.activeWizard.id){loadWizardConfirmedMethods();return;}
  if(!state.wizardConfirmedMethods){list.innerHTML='<p class="skill-meta">正在读取已确认写法</p>';updateWizardMethodSelection();return;}
  const groups=new Map();
  state.wizardConfirmedMethods.forEach(item=>{
    if(!groups.has(item.source_id))groups.set(item.source_id,{title:item.source_title||"参考资料",items:[]});
    groups.get(item.source_id).items.push(item);
  });
  list.innerHTML=groups.size?[...groups.values()].map((group,index)=>`<details class="wizard-method-group" ${index===0?"open":""}><summary><span>《${escapeHtml(group.title)}》</span><small>${group.items.length} 条已确认写法</small></summary><div>${group.items.map(item=>`<label class="wizard-method-item"><input type="checkbox" value="${escapeHtml(item.id)}" ${state.selectedWizardMethods.has(item.id)?"checked":""}><span><strong>${escapeHtml(item.name)}</strong><p>${escapeHtml(item.use||"用于后续创作安排")}</p></span></label>`).join("")}</div></details>`).join(""):'<p class="skill-meta">学习库里还没有可直接带入的已确认写法。</p>';
  list.querySelectorAll("input").forEach(input=>input.addEventListener("change",()=>{
    if(input.checked&&state.selectedWizardMethods.size>=WIZARD_METHOD_LIMIT){input.checked=false;updateWizardMethodSelection();return;}
    if(input.checked)state.selectedWizardMethods.add(input.value);else state.selectedWizardMethods.delete(input.value);
    updateWizardMethodSelection();
  }));
  updateWizardMethodSelection();
}
function setWizardMethodSelectionStatus(message,kind=""){
  const status=$("#wizard-method-selection-status");if(!status)return;
  status.className=`wizard-method-selection-status ${kind}`.trim();
  status.textContent=message;
}
function updateWizardMethodSelection(){
  const count=state.selectedWizardMethods.size,total=state.wizardConfirmedMethods?.length||0,atLimit=count>=WIZARD_METHOD_LIMIT;
  const counter=$("#wizard-method-count");if(counter)counter.textContent=`已选 ${count}/12 条写法`;
  $("#wizard-confirmed-method-list")?.querySelectorAll('input[type="checkbox"]').forEach(input=>{input.disabled=atLimit&&!input.checked;});
  if(count>WIZARD_METHOD_LIMIT)setWizardMethodSelectionStatus("已选写法超过 12 条，请取消多余写法后再创建作品。","error");
  else if(atLimit)setWizardMethodSelectionStatus("一次最多带入 12 条写法，可以取消一条后再选。","limit");
  else if(total>WIZARD_METHOD_LIMIT)setWizardMethodSelectionStatus(`共有 ${total} 条已确认写法，请明确选择最多 12 条。`);
  else setWizardMethodSelectionStatus(count?`已保留 ${count} 条写法，创建时只会提交这些选择。`:"可以继续选择要用于新作品的写法。");
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
async function refreshProjectsAfterConfirmation(project){
  let refreshed;
  try{refreshed=await api("/api/projects");}
  catch{refreshed=state.projects;}
  const unique=new Map();
  [project,...refreshed,...state.projects].forEach(item=>{if(item&&!unique.has(item.id))unique.set(item.id,item);});
  state.projects=[...unique.values()];
  state.activeProject=state.projects.find(item=>item.id===project.id)||project;
  renderProjects();
}
async function openProjectOutlineGenerator(projectId){
  await navigateToView("learning");
  switchLearningView("application");
  const project=state.projects.find(item=>item.id===projectId);
  if(project&&state.activeProject?.id!==projectId){stopRunMonitor();resetRevisionWorkspace();}
  if(project)state.activeProject=project;
  const select=$("#learning-project");
  select.innerHTML=state.projects.length?state.projects.map(item=>`<option value="${item.id}">${escapeHtml(item.title)}</option>`).join(""):'<option value="">请先创建作品</option>';
  select.value=projectId;
  $("#active-project").value=projectId;
  $("#materials-project").value=projectId;
  state.projectLearning=null;state.effectiveRules=null;state.outlines=null;state.activeOutlineCandidateId=null;state.outlineComparison=null;
  if(!await loadProjectLearning())throw new Error("selection_changed");
  renderLearning();
  select.value=projectId;
  const form=$("#outline-generate-form");
  form.focus({preventScroll:true});
  form.scrollIntoView({block:"start"});
}
async function generateInitialOutline(projectId){
  try{await openProjectOutlineGenerator(projectId);}
  catch{showInitialOutlineFailure(projectId);return;}
  setOutlineOperationStatus("busy","正在生成第一版候选大纲","规划模型正在把已确认写法整理成原创大纲，完成后由你决定是否采用。");
  try{
    await api(`/api/projects/${projectId}/learning/generate-outline`,{method:"POST",body:JSON.stringify({brief:"根据已确认写法和当前新故事设定，生成第一版原创候选大纲；不得复用来源作品的人物、设定、独特表达和具体情节。"})});
    await loadProjectLearning();
    setOutlineOperationStatus("success","第一版候选大纲已生成","打开全文查看，确认后才会成为正式大纲。");
  }catch{showInitialOutlineFailure(projectId);}
}
function showInitialOutlineFailure(projectId){
  const shell=$("#outline-operation-status");if(!shell)return;
  shell.className="outline-operation-status error";
  shell.innerHTML='<strong>作品已经创建，可以稍后重试</strong><span>作品资料和已选写法都已保留；候选大纲不会覆盖正式大纲或正文。</span><button class="secondary outline-retry-action" type="button">前往作品应用重新生成</button>';
  shell.querySelector(".outline-retry-action").addEventListener("click",async()=>{
    try{await openProjectOutlineGenerator(projectId);}
    catch{showInitialOutlineFailure(projectId);}
  });
}
function clearConfirmedWizard(wizardId){
  state.activeWizard=null;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set();state.wizardSourceReferenceId=null;state.wizardAutoOutline=false;
  state.wizards=state.wizards.filter(item=>item.id!==wizardId);
  $("#wizard-shell").hidden=true;$("#wizard-launcher").hidden=false;$("#wizard-confirm").disabled=false;
  renderWizardDrafts();
}
function wizardSelectionErrorMessage(error){
  const readableCodes=new Set(["invalid_learning_selection","reference_learning_not_ready","wizard_confirmation_changed","wizard_incomplete","invalid_market_baseline"]);
  const message=String(error?.message||"").trim();
  return readableCodes.has(error?.code)&&/[\u3400-\u9fff]/.test(message)&&!/[A-Za-z]/.test(message)
    ? message
    : "作品创建没有完成，请稍后重试。";
}
async function startWizardFromReference(referenceIds=[]) {
  if(state.referenceSelectionBusy)return;
  referenceIds=[...new Set(referenceIds.filter(Boolean))];
  const sources=referenceIds.map(id=>state.references.find(item=>item.id===id));
  if(sources.some(item=>!item)){
    setReferenceSelectionStatus("error","失败","有一篇所选资料不存在。所选资料会继续保留，请刷新后重新选择。");
    toast("有一篇所选资料不存在，请刷新后重新选择。");
    return;
  }
  if(sources.some(item=>!creatableReferenceTypes.has(item.content_type))){
    setReferenceSelectionStatus("error","不能创建作品",`${referenceCreationUnavailable}。所选资料会继续保留，请清除后重新选择。`);
    toast(referenceCreationUnavailable);
    return;
  }
  const mode=document.querySelector('input[name="wizard-mode"]:checked').value;
  if(referenceIds.length){
    referenceIds.forEach(id=>state.selectedReferenceIds.add(id));
    state.referenceSelectionBusy=true;
    setReferenceSelectionStatus("busy","正在检查所选资料","只检查本地写法，不会调用模型。");
    renderReferences();
  }
  try {
    const missingLocalIds=referenceIds.filter(id=>!state.mechanisms.some(item=>item.source_id===id&&(item.data.analysis_origin||"local")!=="model"));
    let localPreparationFailed=false;
    if(missingLocalIds.length){
      const titles=sources.filter(item=>missingLocalIds.includes(item.id)).map(item=>`《${item.title}》`).join("、");
      setReferenceSelectionStatus("busy","正在完成本地提炼",`${titles}还没有本地写法，正在逐篇提炼；不会调用模型。`);
      const results=await Promise.allSettled(missingLocalIds.map(id=>api(`/api/references/${id}/learn`,{method:"POST"})));
      localPreparationFailed=results.some(item=>item.status==="rejected");
    }
    if(referenceIds.length){
      state.mechanisms=await api("/api/learning/mechanisms?view=all");
      renderWizardDrafts();
      if(localPreparationFailed){
        setReferenceSelectionStatus("error","失败","部分资料没有完成本地提炼。已经完成的结果已保留，所选资料会继续保留；可以稍后重试。");
        toast("部分资料没有完成本地提炼，已经完成的结果已保留。");
        return;
      }
      const waiting=sources.filter(source=>!state.mechanisms.some(item=>item.source_id===source.id&&item.status==="confirmed"));
      if(waiting.length){
        state.referenceSelectionPendingIds=[...referenceIds];
        state.referenceSelectionPendingTitles=waiting.map(item=>item.title);
        setReferenceSelectionStatus("waiting","还需要确认这些资料的候选写法",`${state.referenceSelectionPendingTitles.map(title=>`《${title}》`).join("、")}。所选资料会继续保留。确认完成后，可以继续用刚才选择的资料创建作品。`);
        renderLearning();
        switchLearningView("mechanisms");
        await navigateToView("learning");
        return;
      }
    }
    const wizard=await api("/api/wizards",{method:"POST",body:JSON.stringify({mode,reference_source_ids:referenceIds})});
    const confirmedFromSources=state.mechanisms.filter(item=>referenceIds.includes(item.source_id)&&item.status==="confirmed").map(item=>item.id);
    state.activeWizard=wizard;state.wizardStep=0;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set();state.wizardSourceReferenceId=referenceIds[0]||null;state.wizardAutoOutline=Boolean(referenceIds.length&&$("#wizard-auto-outline")?.checked);state.wizards.unshift(wizard);
    if(referenceIds.length){
      referenceIds.forEach(id=>state.selectedReferenceIds.delete(id));
      clearReferenceReadinessNotice();
      setReferenceSelectionStatus("success","已完成",confirmedFromSources.length>WIZARD_METHOD_LIMIT?`建书向导已创建，共有 ${confirmedFromSources.length} 条确认写法；请在确认页明确选择最多 12 条。`:`建书向导已创建，确认页会保留这 ${confirmedFromSources.length} 条确认写法。`);
    }
    await navigateToView("projects");
    renderWizard();
    if(referenceIds.length)toast(confirmedFromSources.length>WIZARD_METHOD_LIMIT?`共有 ${confirmedFromSources.length} 条确认写法，请在确认页自行选择`:`确认页会保留 ${confirmedFromSources.length} 条写法；请补充新故事的基本信息`);
  } catch(error) {
    console.error("Reference wizard preparation failed",error);
    if(referenceIds.length){
      setReferenceSelectionStatus("error","失败","资料准备或建书向导创建没有完成。所选资料会继续保留，可以稍后重试。");
      toast("资料准备或建书向导创建没有完成，所选资料已保留。");
    }
    else toast("建书向导创建失败，请稍后重试。");
  } finally {
    state.referenceSelectionBusy=false;
    renderReferences();
  }
}
$("#start-wizard").addEventListener("click",()=>{
  const referenceId=$("#wizard-reference").value;
  startWizardFromReference(referenceId?[referenceId]:[]);
});
$("#wizard-drafts").addEventListener("change",()=>updateWizardDraftControls());
$("#continue-wizard-draft").addEventListener("click",async()=>{
  const wizardId=$("#wizard-drafts").value;if(!wizardId)return;
  const button=$("#continue-wizard-draft");button.disabled=true;
  try{
    state.activeWizard=await api(`/api/wizards/${wizardId}`);state.wizardStep=0;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set();state.wizardSourceReferenceId=state.activeWizard.schema?.creation_context?.reference_source_ids?.[0]||null;renderWizard();$("#wizard-draft-status").textContent="草稿已打开，可以继续填写。";
  }catch(error){$("#wizard-draft-status").textContent="草稿读取失败，请刷新后重试。";toast("草稿读取失败，请刷新后重试。");updateWizardDraftControls();}
});
$("#delete-wizard-draft").addEventListener("click",async()=>{
  const wizardId=$("#wizard-drafts").value;if(!wizardId)return;
  if(!confirm("只删除这份未完成的开书资料，不会删除任何作品。"))return;
  const select=$("#wizard-drafts"),continueButton=$("#continue-wizard-draft"),deleteButton=$("#delete-wizard-draft");
  select.disabled=true;continueButton.disabled=true;deleteButton.disabled=true;$("#wizard-draft-status").className="skill-meta";$("#wizard-draft-status").textContent="正在删除草稿";
  try{
    const result=await api(`/api/wizards/${wizardId}`,{method:"DELETE"});
    if(result?.id!==wizardId)throw new Error("unexpected");
    state.wizards=state.wizards.filter(item=>item.id!==wizardId);
    if(state.activeWizard?.id===wizardId){state.activeWizard=null;state.wizardConfirmedMethods=null;state.wizardMethodsFor=null;state.selectedWizardMethods=new Set();state.wizardSourceReferenceId=null;$("#wizard-shell").hidden=true;$("#wizard-launcher").hidden=false;}
    renderWizardDrafts();$("#wizard-draft-status").textContent="草稿已删除，作品和其他草稿都没有变化。";
  }catch(error){select.disabled=false;$("#wizard-draft-status").className="skill-meta error-text";$("#wizard-draft-status").textContent=wizardDraftErrorMessage(error);updateWizardDraftControls();}
});
$("#wizard-back").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep--; renderWizard(); });
$("#wizard-next").addEventListener("click", async () => { await saveWizardStep(); state.wizardStep++; renderWizard(); });
$("#wizard-analyze").addEventListener("click", async () => { try { await saveWizardStep(); state.activeWizard=await api(`/api/wizards/${state.activeWizard.id}/analyze`,{method:"POST"}); state.wizardStep=state.activeWizard.schema.steps.length-1; renderWizard(); toast(state.activeWizard.status === "ready" ? "关键资料完整" : "已生成必要追问"); } catch(error) { toast(error.message); } });
$("#wizard-confirm").addEventListener("click", async () => {
  const button=$("#wizard-confirm"),wizardId=state.activeWizard?.id;
  if(!wizardId)return;
  button.disabled=true;
  let project,autoOutline=false;
  try {
    await saveWizardStep();
    const selected=[...state.selectedWizardMethods];
    autoOutline=Boolean(state.wizardAutoOutline&&selected.length);
    project=await api(`/api/wizards/${wizardId}/confirm`,{method:"POST",body:JSON.stringify({selected_mechanism_ids:selected})});
  }catch(error){
    const message=wizardSelectionErrorMessage(error);
    setWizardMethodSelectionStatus(message,"error");
    toast(message);
    button.disabled=false;
    return;
  }
  clearConfirmedWizard(wizardId);
  await refreshProjectsAfterConfirmation(project);
  if(autoOutline)await generateInitialOutline(project.id);
  else{
    await openProjectOutlineGenerator(project.id);
    setOutlineOperationStatus("","作品已创建，先准备大纲","人物、设定和正文都不会自动生成。请先生成或选择候选大纲，再由你确认正式版本。");
  }
  toast("作品已创建，请先确认正式大纲");
});

async function run(path, body) {
  if (!state.activeProject) return toast("请先创建作品");
  const projectId=state.activeProject.id,workbenchGeneration=state.workbenchGeneration;
  if(state.activeRun||state.runStartingProjectId)return toast("任务正在启动或运行，请不要重复点击。");
  state.runStartingProjectId=projectId;
  const box = $("#run-state"); box.className = "run-state busy"; box.textContent = "飞轮运行中，请保持此页面打开...";
  $("#workbench-task-progress").hidden=false;
  renderWorkbenchTaskState();
  let startFailed=false;
  try {
    const result = await api(path, {method:"POST", body:body ? JSON.stringify(body) : undefined});
    if(workbenchContextMatches(projectId,workbenchGeneration))monitorRun(result,projectId,workbenchGeneration);
  }
  catch(error) {
    startFailed=true;
    const message=readableRunMessage(error.message||"任务没有启动，请稍后重试。");
    if(workbenchContextMatches(projectId,workbenchGeneration)){box.className="run-state error";box.textContent=`任务没有启动：${message}`;toast(message);}
  }finally{
    if(state.runStartingProjectId===projectId)state.runStartingProjectId=null;
    if(workbenchContextMatches(projectId,workbenchGeneration)){
      renderWorkbenchTaskState();
      if(startFailed)$("#workbench-task-progress").hidden=false;
    }
  }
}
const polishRecoveryMessages={
  polish_compact_retry:"正在精简要求后重新润色本段",
  polish_compact_fallback:"首选模型没有返回正文，正在使用备用模型",
  polish_input_compact_retry:"输入超出当前模型上下文，正在保留叙事权威后压缩建议重试",
  polish_output_limit_retry:"供应商截断了本段输出，正在同一路由扩大输出空间重试",
  polish_transport_retry:"润色请求遇到网络波动，正在同一路由重试",
  polish_configured_fallback:"首选润色路由未产生可用正文，正在使用备用路由",
  polish_segment_split:"当前片段输出仍受限，正在按段落边界拆分后重试",
  polish_targeted_repair:"本段出现有证据的局部问题，正在进行小范围定向修复",
  polish_style_allowance:"本段局部节奏符合项目文风规则，已通过验收",
  polish_capacity_preserved:"当前父段无法安全拆分，已保留原文并继续",
  polish_segment_preserved:"本段未完成精修，已保留原文并继续",
};
const hiddenRunEventTypes=new Set(["polish_segment_route","polish_circuit_opened","polish_max_tokens_retry"]);
function polishProgressMetadata(item) {
  const metadata=item?.metadata||{};
  const completed=Number(metadata.completed),total=Number(metadata.total),preserved=Number(metadata.preserved);
  if(![completed,total,preserved].every(Number.isFinite)||completed<0||total<=0||preserved<0||completed>total)return null;
  return {completed,total,preserved};
}
function polishRunProgress(events,status) {
  const latest=[...events].reverse().find(item=>item.event_type==="polish_segment_progress"||polishRecoveryMessages[item.event_type]);
  const progress=[...events].reverse().find(item=>item.event_type==="polish_segment_progress");
  if(!latest)return "";
  const metadata=polishProgressMetadata(progress);
  const {completed,total,preserved}=metadata||{};
  const parts=[];
  if(isActiveRunStatus(status)&&latest.event_type!=="polish_segment_progress")parts.push(polishRecoveryMessages[latest.event_type]);
  if(metadata)parts.push(`已完成 ${completed} / ${total} 段，其中 ${preserved} 段保留原文`);
  const resumable=["failed","cancelled","interrupted"].includes(status);
  if(resumable&&preserved>0)parts.push("继续运行时只处理未完成片段");
  return parts.join("；");
}
function polishRunEventMessage(item) {
  if(item.event_type==="polish_segment_progress"){
    const metadata=polishProgressMetadata(item);
    if(!metadata)return readableRunMessage(item.message);
    return `已完成 ${metadata.completed} / ${metadata.total} 段，其中 ${metadata.preserved} 段保留原文`;
  }
  return polishRecoveryMessages[item.event_type]||readableRunMessage(item.message||`${item.event_type||"event"}: 未返回可用诊断信息`);
}
function renderRunLog(events) {
  const visibleEvents=events.filter(item=>!hiddenRunEventTypes.has(item.event_type)).filter(
    (item,index,items)=>index===0||item.severity!=="error"||items[index-1].severity!=="error"||
      polishRunEventMessage(item)!==polishRunEventMessage(items[index-1])
  );
  $("#run-log").innerHTML = visibleEvents.length ? visibleEvents.map(item => {
    return `<div class="log-row ${escapeHtml(item.severity)}"><span class="log-time">${escapeHtml(formatLocalTimestamp(item.created_at, true))}</span><span class="log-stage">${escapeHtml(runLabel(item.stage || item.event_type))}</span><span>${escapeHtml(polishRunEventMessage(item))}</span></div>`;
  }).join("") : '<p class="skill-meta">等待第一条运行日志...</p>';
  $("#run-log").scrollTop = $("#run-log").scrollHeight;
}
function initializationCandidateNotice(events) {
  const event=[...events].reverse().find(item=>item.event_type==="skill_failed"&&item.metadata?.proposal_summary);
  if(!event)return "";
  const summary=event.metadata.proposal_summary||{},counts=summary.counts||{};
  const reusable=Number(summary.retainable_count??((counts.pending||0)+(counts.retained||0)));
  const repair=Number(summary.repair_count??counts.failed??0);
  const duplicates=Number(summary.duplicate_count??counts.superseded??0);
  const missing=Number(summary.missing_count??(summary.missing_items||[]).length);
  const missingItems=Array.isArray(summary.missing_items)?summary.missing_items.filter(Boolean):[];
  const parts=[`${Math.max(0,reusable)} 份可继续使用`];
  if(repair>0)parts.push(`${repair} 份需要自动修复`);
  if(duplicates>0)parts.push(`${duplicates} 份重复内容已隔离`);
  if(missing>0)parts.push(`${missing} 项仍需补写`);
  const title=reusable>0?"失败前生成的资料已经保留":repair>0?"生成的资料需要修复后再使用":"本阶段没有可复用的新资料";
  const missingDetail=missingItems.length?`<details class="candidate-missing"><summary>查看仍需补写的内容</summary><ul>${missingItems.slice(0,3).map(item=>`<li>${escapeHtml(item)}</li>`).join("")}</ul>${missingItems.length>3?`<small>还有 ${missingItems.length-3} 项，继续初始化时会一起处理。</small>`:""}</details>`:"";
  return `<div class="context-tools warning"><strong>${title}</strong><span>${escapeHtml(parts.join(" · "))}<br>正式人物、设定和剧情资料没有被修改；再次继续初始化时，系统会先复用可用内容并修复其余内容。</span>${missingDetail}</div>`;
}
function renderRunContext(detail) {
  const events=detail.events || []; const loaded=new Map();
  events.filter(item => ["skills_loaded","learning_context_loaded"].includes(item.event_type)).forEach(item => loaded.set(item.stage,{...(loaded.get(item.stage)||{}),...(item.metadata||{})}));
  const pendingFallbacks=new Set(); const completed=[];
  events.forEach(item => { if(item.event_type === "model_fallback") pendingFallbacks.add(item.stage); if(["stage_completed","skill_completed"].includes(item.event_type)) { completed.push({...item,usedFallback:pendingFallbacks.has(item.stage)}); pendingFallbacks.delete(item.stage); } });
  const stages=completed.map(item => { const meta=item.metadata || {}; const context=loaded.get(item.stage) || {}; const confirmed=[...(context.confirmed_context||meta.confirmed_context||[])]; if("prose_rules" in context||"creative_methods" in context)confirmed.push(`${Number(context.prose_rules||0)} 条文笔规则`,`${Number(context.creative_methods||0)} 条创作方法`); return `<div class="context-stage"><div><strong>${escapeHtml(runLabel(item.stage))}</strong><span>${escapeHtml(meta.model_name || "未记录模型")}${item.usedFallback ? " · 已回退" : ""}</span></div><dl><dt>写作能力</dt><dd>${escapeHtml((context.skills || meta.skills || []).join("、") || "无")}</dd>${confirmed.length?`<dt>本阶段参考</dt><dd>${escapeHtml(confirmed.join("、"))}</dd>`:""}<dt>提示词</dt><dd>${Number(context.prompt_characters || 0).toLocaleString()} 字符</dd><dt>约束</dt><dd>${Number(context.constraint_characters || 0).toLocaleString()} 字符</dd><dt>模型用量</dt><dd>${Number(meta.input_tokens || 0).toLocaleString()} 输入 · ${Number(meta.output_tokens || 0).toLocaleString()} 输出</dd><dt>执行</dt><dd>${escapeHtml(runLabel(meta.execution_mode || "普通请求"))}</dd></dl></div>`; });
  const tools=detail.tool_receipts || [];
  const audit=detail.quality_report?.final_review_evidence; const counts=audit?.reconciliation_counts || {};
  const detailAnalysis=audit?.detail_analysis;
  const detailStatus=detailAnalysis ? `<div class="context-tools"><strong>${detailAnalysis.performed?"已单独复核":"无需单独复核"}</strong><span>${escapeHtml(detailAnalysis.message||"系统已根据本地检查决定是否需要详细事件和伏笔复核")}</span></div>` : "";
  const quality=audit ? `<div class="context-tools"><strong>${audit.review_mode==="incremental"?"关联窗口复核":"全文终审"}</strong><span>覆盖 ${Math.round(Number(audit.coverage || 0)*100)}% · ${Number(audit.reviewed_windows || 0)}/${Number(audit.window_count || 0)} 窗口 · 节省约 ${Number(audit.estimated_saved_input_characters || 0).toLocaleString()} 输入字符${(audit.fallback_reasons || []).length ? ` · 全文回退：${escapeHtml(audit.fallback_reasons.join("、"))}` : ""} · 已解决 ${Number(counts.resolved || 0)} · 部分解决 ${Number(counts.partially_resolved || 0)} · 未解决 ${Number(counts.unresolved || 0)}${(audit.gate_reasons || []).length ? ` · 阻断：${escapeHtml(audit.gate_reasons.join("、"))}` : ""}</span></div>` : "";
  const issues=detail.quality_report?.review?.issues||detail.quality_report?.issues||[];
  const issueLedger=issues.length?`<details class="quality-ledger"><summary><span><strong>问题返修台账</strong><small>${issues.length} 项 · 未解决优先</small></span><span>展开</span></summary><div class="ledger-list">${[...issues].sort((a,b)=>(a.status==="resolved")-(b.status==="resolved")).map(item=>`<details><summary><span class="ledger-status ${item.status==="resolved"?"resolved":""}">${item.status==="resolved"?"已解决":"待处理"}</span>${escapeHtml(findingLabel(item.issue_id||item.category||"问题"))}</summary><p><strong>证据：</strong>${escapeHtml(item.evidence||"未提供")}</p><p><strong>修复目标：</strong>${escapeHtml(item.repair_goal||item.action||"待确认")}</p></details>`).join("")}</div></details>`:"";
  const recovery=detail.quality_report?.final_review_recovery;
  const failureDetail=detail.quality_report?.failure_detail;
  const notice=recovery?.attempted ? `<div class="context-tools ${recovery.succeeded ? "success" : "warning"}"><strong>${recovery.succeeded ? "终审报告已恢复" : "终审报告仍不完整"}</strong><span>${escapeHtml(recovery.message || "最佳稿已保留，可以重新终审")}</span></div>` : failureDetail?.kind === "malformed_json" ? '<div class="context-tools warning"><strong>终审返回内容不完整</strong><span>系统没有采用半份报告，最佳稿已保留；可以重新终审。</span></div>' : "";
  const learning=events.find(item=>item.event_type==="initialization_learning_snapshot")?.metadata;
  const stageCounts=learning?.stage_counts||{};
  const learningStages=Object.entries(stageCounts).filter(([stage])=>stage!=="story-init").map(([stage,count])=>`${runLabel(stage)}：${Number(count.prose_rules||0)} 条文笔、${Number(count.creative_methods||0)} 条方法`).join("；");
  const learningContext=learning ? `<div class="context-tools success"><strong>本次参考的文笔和创作方法</strong><span>${learning.prose_baseline?`基础文笔第 ${Number(learning.prose_baseline)} 版`:`没有已生效的基础文笔`} · ${learning.creative_blueprint?`创作蓝图第 ${Number(learning.creative_blueprint)} 版`:`没有已生效的创作蓝图`}${learningStages?`<br>${escapeHtml(learningStages)}`:""}${Number(learning.skipped_conflicts||0)?`<br>已跳过 ${Number(learning.skipped_conflicts)} 条与当前叙事视角冲突的规则。`:""}<br>正式大纲和已确认设定优先，不会在这里被改写。</span></div>` : "";
  const initializationCandidates=initializationCandidateNotice(events);
  $("#run-context").innerHTML=(stages.join("") || '<p class="skill-meta">本次运行尚无已完成阶段</p>') + learningContext + initializationCandidates + notice + quality + detailStatus + issueLedger + (tools.length ? `<div class="context-tools"><strong>工具调用记录</strong><span>${tools.length} 条 · ${escapeHtml([...new Set(tools.map(item => runLabel(item.execution_mode)))].join("、"))}</span></div>` : "");
}
document.querySelectorAll("[data-run-tab]").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll("[data-run-tab]").forEach(item => item.classList.toggle("active",item === button));
  $("#run-log").hidden=button.dataset.runTab !== "log"; $("#run-context").hidden=button.dataset.runTab !== "context";
}));
function showRunDetail(detail) {
  renderRunLog(detail.events || []);
  renderRunContext(detail);
  const active=isActiveRunStatus(detail.status);
  const initialization=detail.workflow === "initialize-skills";
  const qualityRejected=isQualityRejected(detail);
  $("#run-state").className=`run-state ${active ? "busy" : qualityRejected ? "warning" : detail.status === "failed" ? "error" : detail.status}`;
  const progress=polishRunProgress(detail.events || [],detail.status);
  const message=active ? `正在执行：${runLabel(detail.current_stage || detail.workflow)}` : detail.status === "completed" ? (initialization ? "初始化及校验已完成，可以开始写作" : "任务执行完成") : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : detail.status === "failed" ? `${initialization ? "初始化" : "任务"}失败：${readableRunMessage(detail.error || "请查看日志")}` : `${runStatusLabel(detail)}：${readableRunMessage(detail.error || "请查看日志")}`;
  $("#run-state").textContent=progress?`${message} · ${progress}`:message;
}
async function monitorRun(runRecord,projectId=runRecord.project_id||state.activeProject?.id,workbenchGeneration=state.workbenchGeneration) {
  clearTimeout(state.pollTimer);
  const runId=runRecord.id;
  const monitorGeneration=++state.runMonitorGeneration;
  state.activeRun=runId;state.activeRunProjectId=projectId;
  state.workbenchRuns=[{...runRecord,status:runRecord.status||"queued"},...state.workbenchRuns.filter(item=>item.id!==runId)];
  $("#run-cancel").hidden=false;
  renderWorkbenchTaskState();
  const poll = async () => {
    if(state.runMonitorGeneration!==monitorGeneration||state.activeRun!==runId||!workbenchContextMatches(projectId,workbenchGeneration))return;
    try {
      const detail=await api(`/api/runs/${runId}`);
      if(state.runMonitorGeneration!==monitorGeneration||state.activeRun!==runId||!workbenchContextMatches(projectId,workbenchGeneration))return;
      state.workbenchRuns=[detail,...state.workbenchRuns.filter(item=>item.id!==detail.id)];
      renderRunLog(detail.events || []); renderRunContext(detail);
      if (detail.workflow==="materials-audit") renderMaterialAudit(detail);
      const active=isActiveRunStatus(detail.status); const qualityRejected=isQualityRejected(detail); $("#run-state").className=`run-state ${active ? "busy" : qualityRejected ? "warning" : detail.status === "failed" ? "error" : detail.status}`;
      const progress=polishRunProgress(detail.events || [],detail.status);
      const message=detail.status === "cancelling" ? "正在终止当前阶段..." : active ? `正在执行：${runLabel(detail.current_stage || detail.workflow)}` : detail.status === "completed" ? "执行完成" : detail.status === "cancelled" ? "本次任务已终止，作品仍可继续写作" : qualityRejected ? "质量审核未通过：草稿和审核报告已保留，可修改后重试" : `${runStatusLabel(detail)}：${readableRunMessage(detail.error || "请查看日志")}`;
      $("#run-state").textContent=progress?`${message} · ${progress}`:message;
      renderWorkbenchTaskState();
      if (active) state.pollTimer=setTimeout(poll,900); else { state.activeRun=null; $("#run-cancel").hidden=true; await renderActiveProject(); if (detail.status === "completed") toast("飞轮执行完成"); }
    } catch(error) { if(state.runMonitorGeneration!==monitorGeneration||!workbenchContextMatches(projectId,workbenchGeneration))return;$("#run-state").className="run-state error"; $("#run-state").textContent=readableRunMessage(error.message); $("#run-cancel").hidden=true;renderWorkbenchTaskState(); }
  };
  await poll();
}
$("#run-cancel").addEventListener("click",async()=>{
  const runId=state.activeRun,projectId=state.activeRunProjectId,generation=state.workbenchGeneration;
  if(!runId||!projectId)return;
  try{
    await api(`/api/runs/${runId}/cancel`,{method:"POST"});
    if(state.activeRun===runId&&workbenchContextMatches(projectId,generation))$("#run-state").textContent="正在终止当前阶段...";
  }catch{
    if(state.activeRun===runId&&workbenchContextMatches(projectId,generation)){
      $("#run-state").className="run-state error";$("#run-state").textContent="终止请求没有完成，请稍后重试。";
    }
  }
});
$("#initialize-project").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/initialize-skills`));
$("#run-short").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/short`));
$("#run-setup").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/setup`));
$("#run-chapter").addEventListener("click", () => { const chapter_goal = $("#chapter-goal").value.trim(); if (!chapter_goal) return toast("请填写本章目标"); run(`/api/projects/${state.activeProject.id}/runs/chapter`, {chapter_goal}); });
$("#open-manuscript").addEventListener("click", async () => {
  if (!state.activeProject) return;
  const projectId=state.activeProject.id,generation=state.workbenchGeneration;
  try {
    const result = await api(`/api/projects/${projectId}/manuscript`);
    if(!workbenchContextMatches(projectId,generation))return;
    $("#manuscript").textContent = result.content || "尚未生成正文";
    const panel = $("#manuscript-panel");
    panel.hidden = false;
    panel.scrollIntoView({behavior:"smooth",block:"start"});
  } catch { if(workbenchContextMatches(projectId,generation))toast("正文读取失败，请稍后重试。"); }
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
  $("#role-bindings").innerHTML = Object.entries(roles).map(([role,label]) => {
    const requiresTools=toolRequiredRoles.has(role);
    const toolNote=requiresTools ? "需要工具" : "不需要工具";
    const toolTitle=requiresTools ? "这个角色会写入项目资料，主模型和备用模型都必须支持工具调用" : "这个角色不支持工具调用也能正常工作";
    return `<div class="binding-row"><div class="binding-role"><strong>${label}</strong><small class="role-tool-note ${requiresTools ? "required" : ""}" title="${toolTitle}">${toolNote}</small></div><label class="binding-control"><span>主模型</span><select id="binding-primary-${role}"><option value="">请选择模型</option>${options}</select></label><label class="binding-control"><span>备用模型</span><select id="binding-fallback-${role}"><option value="">使用程序默认回退</option>${options}</select></label><button class="secondary" data-bind="${role}">保存</button></div>`;
  }).join("");
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
