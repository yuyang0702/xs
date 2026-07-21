const state = { projects: [], providers: [], skills: [], activeProject: null };
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

document.querySelectorAll(".nav-item").forEach(button => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item,.view").forEach(el => el.classList.remove("active"));
  button.classList.add("active"); $(`#${button.dataset.view}`).classList.add("active");
  $("#view-title").textContent = button.textContent;
}));

async function loadAll() {
  [state.projects, state.providers, state.skills] = await Promise.all([api("/api/projects"), api("/api/providers"), api("/api/skills")]);
  renderProjects(); renderProviders(); renderSkills(); renderBindings();
}
function renderProjects() {
  const select = $("#active-project");
  select.innerHTML = state.projects.length ? state.projects.map(p => `<option value="${p.id}">${escapeHtml(p.title)}</option>`).join("") : '<option value="">尚无作品</option>';
  if (!state.activeProject || !state.projects.some(p => p.id === state.activeProject.id)) state.activeProject = state.projects[0] || null;
  if (state.activeProject) select.value = state.activeProject.id;
  renderActiveProject();
}
async function renderActiveProject() {
  const p = state.activeProject;
  $("#short-actions").hidden = !p || p.mode !== "short"; $("#long-actions").hidden = !p || p.mode !== "long";
  $("#project-summary").innerHTML = p ? `<div class="metric"><strong>${escapeHtml(p.title)}</strong><span>当前作品</span></div><div class="metric"><strong>${p.mode === "short" ? "短篇" : "长篇"}</strong><span>模式</span></div><div class="metric"><strong>${Number(p.target_words).toLocaleString()}</strong><span>目标字数</span></div><div class="metric"><strong>${escapeHtml(p.genre)}</strong><span>题材</span></div>` : '<span>先创建一部作品。</span>';
  if (!p) { $("#run-list").innerHTML = ""; return; }
  const runs = await api(`/api/projects/${p.id}/runs`);
  $("#run-list").innerHTML = runs.length ? runs.map(r => `<div class="run-row"><div><strong>${escapeHtml(r.workflow)}</strong><div class="skill-meta">${escapeHtml(r.current_stage || "-")} · ${escapeHtml(r.created_at)}</div></div><span class="status ${r.status}">${escapeHtml(r.status)}</span></div>`).join("") : '<p class="skill-meta">暂无运行记录</p>';
}
$("#active-project").addEventListener("change", event => { state.activeProject = state.projects.find(p => p.id === event.target.value); renderActiveProject(); });

$("#project-form").addEventListener("submit", async event => {
  event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); data.target_words = Number(data.target_words);
  try { const project = await api("/api/projects", {method:"POST", body:JSON.stringify(data)}); state.projects.unshift(project); state.activeProject = project; renderProjects(); toast("作品已创建"); document.querySelector('[data-view="workbench"]').click(); }
  catch (error) { toast(error.message); }
});

async function run(path, body) {
  if (!state.activeProject) return toast("请先创建作品");
  const box = $("#run-state"); box.className = "run-state busy"; box.textContent = "飞轮运行中，请保持此页面打开...";
  try { const result = await api(path, {method:"POST", body:body ? JSON.stringify(body) : undefined}); const detail = await api(`/api/runs/${result.id}`); const receipts = detail.tool_receipts || []; const nativeCount = receipts.filter(r => r.execution_mode === "native_tools" && r.tool_name).length; const fallback = receipts.find(r => r.execution_mode === "degraded_prompt_mode"); const mode = fallback ? `提示降级：${fallback.fallback_reason || "模型不支持工具"}` : `原生工具 ${nativeCount} 次`; box.className = "run-state"; box.textContent = `已完成：${result.id} · ${mode}`; await renderActiveProject(); toast("飞轮执行完成"); }
  catch (error) { box.className = "run-state error"; box.textContent = error.message; }
}
$("#run-short").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/short`));
$("#run-setup").addEventListener("click", () => run(`/api/projects/${state.activeProject.id}/runs/setup`));
$("#run-chapter").addEventListener("click", () => { const chapter_goal = $("#chapter-goal").value.trim(); if (!chapter_goal) return toast("请填写本章目标"); run(`/api/projects/${state.activeProject.id}/runs/chapter`, {chapter_goal}); });
$("#open-manuscript").addEventListener("click", async () => { if (!state.activeProject) return; const result = await api(`/api/projects/${state.activeProject.id}/manuscript`); $("#manuscript").textContent = result.content || "尚未生成正文"; $("#manuscript-panel").hidden = false; });
$("#close-manuscript").addEventListener("click", () => $("#manuscript-panel").hidden = true);

$("#provider-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); try { await api("/api/providers", {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("供应商已保存，API Key 已进入系统凭据库"); } catch(error) { toast(error.message); } });
$("#model-form").addEventListener("submit", async event => { event.preventDefault(); const data = Object.fromEntries(new FormData(event.target)); const provider = data.provider_id; delete data.provider_id; try { await api(`/api/providers/${provider}/models`, {method:"POST", body:JSON.stringify(data)}); event.target.reset(); await loadAll(); toast("模型映射已保存"); } catch(error) { toast(error.message); } });
function renderProviders() {
  $("#model-provider").innerHTML = state.providers.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  $("#provider-list").innerHTML = state.providers.length ? state.providers.map(p => `<div class="data-row"><div><strong>${escapeHtml(p.name)}</strong><div class="skill-meta">${escapeHtml(p.protocol)} · ${escapeHtml(p.base_url)}</div></div><span class="badge">${p.models.length} 个模型</span></div>`).join("") : '<p class="skill-meta">尚未配置供应商</p>';
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
