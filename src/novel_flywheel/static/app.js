const state = { projects: [], trash: [], providers: [], skills: [], wizards: [], activeProject: null, activeWizard: null, wizardStep: 0, activeRun: null, pollTimer: null, interviewWizardId: null, interviewMessages: [], interviewBusy: false };
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
  polish: "精修与去 AI 味", final_review: "独立终审", maintenance: "项目资料更新"
};
const $ = (selector) => document.querySelector(selector);
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","'":"&#39;",'"':"&quot;"}[c]));

async function api(path, options = {}) {
  const response = await fetch(path, {headers:{"Content-Type":"application/json"}, ...options});
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail?.message || body.detail?.code || `HTTP ${response.status}`);
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
document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => showView(button.dataset.view, button.textContent)));
document.querySelectorAll("[data-view-target]").forEach(button => button.addEventListener("click", () => showView(button.dataset.viewTarget)));

async function loadAll() {
  [state.projects, state.trash, state.providers, state.skills, state.wizards] = await Promise.all([api("/api/projects"), api("/api/projects/trash"), api("/api/providers"), api("/api/skills"), api("/api/wizards")]);
  renderProjects(); renderTrash(); renderProviders(); renderSkills(); renderBindings(); renderWizardDrafts();
}
function renderProjects() {
  const select = $("#active-project");
  select.innerHTML = state.projects.length ? state.projects.map(p => `<option value="${p.id}">${escapeHtml(p.title)}</option>`).join("") : '<option value="">尚无作品</option>';
  if (!state.activeProject || !state.projects.some(p => p.id === state.activeProject.id)) state.activeProject = state.projects[0] || null;
  if (state.activeProject) select.value = state.activeProject.id;
  $("#project-list").innerHTML = state.projects.length ? state.projects.map(p => `<article class="project-item"><h3>${escapeHtml(p.title)}</h3><div class="skill-meta">${p.mode === "short" ? "短篇" : "长篇"} · ${escapeHtml(p.genre)} · ${Number(p.target_words).toLocaleString()} 字</div><div class="project-actions"><button class="secondary" data-continue="${p.id}">继续写作</button><button class="secondary danger-text" data-trash="${p.id}">移入回收站</button></div></article>`).join("") : '<p class="skill-meta">尚无作品</p>';
  document.querySelectorAll("[data-continue]").forEach(button => button.addEventListener("click", () => { state.activeProject=state.projects.find(p => p.id === button.dataset.continue); renderProjects(); showView("workbench"); }));
  document.querySelectorAll("[data-trash]").forEach(button => button.addEventListener("click", () => trashProject(button.dataset.trash)));
  renderActiveProject();
}
async function renderActiveProject() {
  const p = state.activeProject;
  $("#short-actions").hidden = !p || p.mode !== "short"; $("#long-actions").hidden = !p || p.mode !== "long";
  $("#project-summary").innerHTML = p ? `<div class="metric"><strong>${escapeHtml(p.title)}</strong><span>当前作品</span></div><div class="metric"><strong>${p.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(p.target_words).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${escapeHtml(p.genre)}</strong><span>题材</span></div>` : '<span>先创建一部作品。</span>';
  $("#trash-project").disabled = !p;
  if (!p) { $("#run-list").innerHTML = ""; return; }
  const runs = await api(`/api/projects/${p.id}/runs`);
  $("#run-list").innerHTML = runs.length ? runs.map(r => `<button class="run-row" data-run-detail="${r.id}"><div><strong>${escapeHtml(r.workflow)}</strong><div class="skill-meta">${escapeHtml(r.current_stage || "-")} · ${escapeHtml(r.created_at)}</div></div><span class="status ${r.status}">${escapeHtml(r.status)}</span></button>`).join("") : '<p class="skill-meta">暂无运行记录</p>';
  document.querySelectorAll("[data-run-detail]").forEach(button => button.addEventListener("click", async () => renderRunLog((await api(`/api/runs/${button.dataset.runDetail}`)).events || [])));
}
$("#active-project").addEventListener("change", event => { state.activeProject = state.projects.find(p => p.id === event.target.value); renderActiveProject(); });

function renderWizardDrafts() {
  const drafts = state.wizards.filter(item => item.status === "draft");
  $("#wizard-drafts").innerHTML = '<option value="">选择草稿</option>' + drafts.map(item => `<option value="${item.id}">${escapeHtml(item.answers?.title?.value || (item.mode === "long" ? "未命名长篇" : "未命名短篇"))}</option>`).join("");
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
  if (state.activeWizard?.id === wizardId) renderInterview();
}
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
  state.interviewBusy=true; renderInterview();
  try {
    await saveWizardStep();
    await api(`/api/wizards/${state.activeWizard.id}/interview`,{method:"POST",body:JSON.stringify({message:message || null})});
    $("#interview-input").value=""; await loadInterview();
  } catch(error) { toast(error.message); }
  finally { state.interviewBusy=false; renderInterview(); }
}
async function applyInterviewSuggestions() {
  const selected=[...document.querySelectorAll("[data-interview-suggestion]:checked")];
  if (!selected.length) return toast("请选择要写回向导的建议");
  const grouped=new Map(); selected.forEach(input => { const list=grouped.get(input.dataset.messageId) || []; list.push(input.value); grouped.set(input.dataset.messageId,list); });
  state.interviewBusy=true; renderInterview();
  try {
    for (const [messageId,fieldIds] of grouped) {
      const result=await api(`/api/wizards/${state.activeWizard.id}/interview/${messageId}/apply`,{method:"POST",body:JSON.stringify({field_ids:fieldIds})});
      state.activeWizard=result.wizard;
    }
    renderWizard(); await loadInterview(); toast("所选建议已写回向导");
  } catch(error) { toast(error.message); }
  finally { state.interviewBusy=false; renderInterview(); }
}
$("#interview-start").addEventListener("click", () => sendInterview(null));
$("#interview-form").addEventListener("submit", event => { event.preventDefault(); const message=$("#interview-input").value.trim(); if (!message) return toast("请先输入你的想法"); sendInterview(message); });
$("#interview-apply").addEventListener("click", applyInterviewSuggestions);
$("#start-wizard").addEventListener("click", async () => { const mode=document.querySelector('input[name="wizard-mode"]:checked').value; try { state.activeWizard=await api("/api/wizards",{method:"POST",body:JSON.stringify({mode})}); state.wizardStep=0; state.wizards.unshift(state.activeWizard); renderWizard(); } catch(error) { toast(error.message); } });
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
  $("#run-log").innerHTML = events.length ? events.map(item => `<div class="log-row ${escapeHtml(item.severity)}"><span class="log-time">${escapeHtml((item.created_at || "").slice(11,19))}</span><span class="log-stage">${escapeHtml(item.stage || item.event_type)}</span><span>${escapeHtml(item.message)}</span></div>`).join("") : '<p class="skill-meta">等待第一条运行日志...</p>';
  $("#run-log").scrollTop = $("#run-log").scrollHeight;
}
async function monitorRun(runRecord) {
  clearTimeout(state.pollTimer); state.activeRun=runRecord.id; $("#run-cancel").hidden=false;
  const poll = async () => {
    try {
      const detail=await api(`/api/runs/${state.activeRun}`); renderRunLog(detail.events || []);
      const active=["queued","running","cancelling"].includes(detail.status); $("#run-state").className=`run-state ${active ? "busy" : detail.status === "failed" ? "error" : detail.status}`;
      $("#run-state").textContent=detail.status === "cancelling" ? "正在终止当前阶段..." : active ? `正在执行：${detail.current_stage || detail.workflow}` : detail.status === "completed" ? "执行完成" : detail.status === "cancelled" ? "本次任务已终止，作品仍可继续写作" : `${detail.status}：${detail.error || "请查看日志"}`;
      if (active) state.pollTimer=setTimeout(poll,900); else { state.activeRun=null; $("#run-cancel").hidden=true; await renderActiveProject(); if (detail.status === "completed") toast("飞轮执行完成"); }
    } catch(error) { $("#run-state").className="run-state error"; $("#run-state").textContent=error.message; $("#run-cancel").hidden=true; }
  };
  await poll();
}
$("#run-cancel").addEventListener("click", async () => { if (!state.activeRun) return; try { await api(`/api/runs/${state.activeRun}/cancel`,{method:"POST"}); $("#run-state").textContent="正在终止当前阶段..."; } catch(error) { toast(error.message); } });
$("#run-short").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/short`));
$("#run-setup").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/setup`));
$("#run-chapter").addEventListener("click", () => { const chapter_goal = $("#chapter-goal").value.trim(); if (!chapter_goal) return toast("请填写本章目标"); run(`/api/projects/${state.activeProject.id}/runs/chapter`, {chapter_goal}); });
$("#open-manuscript").addEventListener("click", async () => { if (!state.activeProject) return; const result = await api(`/api/projects/${state.activeProject.id}/manuscript`); $("#manuscript").textContent = result.content || "尚未生成正文"; $("#manuscript-panel").hidden = false; });
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
  $("#trash-list").innerHTML = state.trash.length ? state.trash.map(item => `<div class="data-row"><div><strong>${escapeHtml(item.title)}</strong><div class="skill-meta">${escapeHtml(item.mode)} · 删除于 ${escapeHtml(item.trashed_at)}</div></div><div class="project-actions"><button class="secondary" data-restore="${item.id}">恢复</button><button class="danger-button" data-permanent="${item.id}">永久删除</button></div></div>`).join("") : '<p class="skill-meta">回收站为空</p>';
  document.querySelectorAll("[data-restore]").forEach(button => button.addEventListener("click", async () => { try { await api(`/api/projects/${button.dataset.restore}/restore`,{method:"POST"}); await loadAll(); toast("作品已恢复"); } catch(error) { toast(error.message); } }));
  document.querySelectorAll("[data-permanent]").forEach(button => button.addEventListener("click", async () => { if (!confirm("永久删除后无法恢复，确定继续？")) return; try { await api(`/api/projects/${button.dataset.permanent}/permanent`,{method:"DELETE"}); await loadAll(); toast("作品已永久删除"); } catch(error) { toast(error.message); } }));
}

$("#provider-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); try { await api("/api/providers", {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("供应商已保存，API Key 已进入系统凭据库"); } catch(error) { toast(error.message); } });
$("#model-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); const provider = data.provider_id; delete data.provider_id; try { await api(`/api/providers/${provider}/models`, {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("模型映射已保存"); } catch(error) { toast(error.message); } });
function renderProviders() {
  $("#model-provider").innerHTML = state.providers.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  $("#provider-list").innerHTML = state.providers.length ? state.providers.map(p => `<div class="data-row"><div><strong>${escapeHtml(p.name)}</strong><div class="skill-meta">${escapeHtml(p.protocol)} · ${escapeHtml(p.base_url)}</div><div class="key-update"><input type="password" autocomplete="new-password" placeholder="${p.has_api_key ? "更新 API Key" : "API Key 已缺失，请重新输入"}" data-key-input="${p.id}"><button class="secondary" data-key-save="${p.id}">保存密钥</button></div>${p.models.map(m => `<div class="model-row"><strong>${escapeHtml(m.display_name)}</strong><div class="model-actions"><button class="secondary" data-probe-provider="${p.id}" data-probe-model="${m.id}" ${p.has_api_key ? "" : "disabled"}>检测模型</button><span id="probe-${m.id}" class="probe-result">${p.has_api_key ? "尚未检测" : "请先更新密钥"}</span></div></div>`).join("")}</div><span class="badge ${p.has_api_key ? "" : "missing"}">${p.has_api_key ? `${p.models.length} 个模型` : "密钥缺失"}</span></div>`).join("") : '<p class="skill-meta">尚未配置供应商</p>';
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
  const options = modelOptions(); $("#role-bindings").innerHTML = Object.entries(roles).map(([role,label]) => `<div class="binding-row"><strong>${label}</strong><select id="binding-${role}"><option value="">请选择模型</option>${options}</select><button class="secondary" data-bind="${role}">保存</button></div>`).join("");
  document.querySelectorAll("[data-bind]").forEach(button => button.addEventListener("click", async () => { const value = $(`#binding-${button.dataset.bind}`).value; if (!value) return toast("请选择模型"); const [primary_provider_id, primary_model_id] = value.split("|"); try { await api(`/api/role-bindings/${button.dataset.bind}`, {method:"PUT", body:JSON.stringify({primary_provider_id,primary_model_id})}); toast("角色绑定已保存"); } catch(error) { toast(error.message); } }));
  api("/api/role-bindings").then(bindings => bindings.forEach(b => { const select = $(`#binding-${b.role}`); if (select) select.value = `${b.primary_provider_id}|${b.primary_model_id}`; }));
}
function renderSkills() {
  $("#skill-list").innerHTML = state.skills.length ? state.skills.map(s => `<div class="data-row"><div><strong>${escapeHtml(s.name)}</strong><div class="skill-meta">${escapeHtml(s.path)}<br>${s.content_hash.slice(0,16)}</div></div><div>${s.executable ? '<span class="badge">执行型</span>' : '<span class="badge">提示词</span>'} ${s.approved ? '<span class="status">已启用</span>' : `<button class="secondary" data-approve="${escapeHtml(s.name)}" data-hash="${s.content_hash}">授权</button>`}</div></div>`).join("") : '<p class="skill-meta">未发现 Skill</p>';
  document.querySelectorAll("[data-approve]").forEach(button => button.addEventListener("click", async () => { try { await api(`/api/skills/${encodeURIComponent(button.dataset.approve)}/approve`, {method:"POST", body:JSON.stringify({content_hash:button.dataset.hash})}); await loadAll(); toast("当前 Skill 版本已授权"); } catch(error) { toast(error.message); } }));
}
$("#refresh").addEventListener("click", () => loadAll().then(() => toast("已刷新")));
loadAll().catch(error => toast(error.message));
