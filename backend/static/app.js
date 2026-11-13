"use strict";

const $ = (id) => document.getElementById(id);
const THEME_KEY = "fred-admin-theme";
const state = {
  sections: [],
  current: null,
  content: "",
  drafts: new Set(),
  busy: false,
  workspaces: [],
  activeWorkspace: "",
  suggested: null,
};

let toastTimer = null;

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function link(url, label) {
  if (!url) return "";
  const safe = esc(url);
  return `<a href="${safe}" target="_blank" rel="noopener">${esc(label || url)}</a>`;
}

function toast(message, kind = "ok") {
  const box = $("toast");
  box.textContent = message;
  box.className = `toast ${kind}`;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => box.classList.add("hidden"), 4500);
}

async function api(method, path, body) {
  const options = { method, headers: {} };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = {};
  try { data = await response.json(); } catch { /* non-JSON */ }
  if (!response.ok) {
    let detail = data.detail || `${method} ${path} failed (HTTP ${response.status})`;
    if (Array.isArray(detail)) {
      detail = detail.map((item) => item.msg || JSON.stringify(item)).join("; ");
    }
    throw new Error(detail);
  }
  return data;
}

function setBusy(on, label) {
  state.busy = on;
  $("btn-publish").disabled = on || !state.drafts.size;
  $("btn-rollback").disabled = on;
  $("btn-workspaces").disabled = on;
  $("btn-save").disabled = on || !state.current;
  document.querySelectorAll(".ws-action").forEach((button) => { button.disabled = on; });
  if (label) $("status").insertAdjacentHTML("afterbegin", `<span class="pill">${esc(label)}</span>`);
}

// ---------------------------------------------------------------- theme

function applyTheme(theme) {
  const value = theme === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = value;
  try { localStorage.setItem(THEME_KEY, value); } catch { /* ignore */ }
  $("btn-theme").textContent = value === "light" ? "🌙 Dark" : "☀ Light";
  const action = value === "light" ? "Switch to dark mode" : "Switch to light mode";
  $("btn-theme").title = action;
  $("btn-theme").setAttribute("aria-label", action);
}

function initTheme() {
  let stored = null;
  try { stored = localStorage.getItem(THEME_KEY); } catch { /* ignore */ }
  applyTheme(stored || "dark");
}

// ---------------------------------------------------------------- status

async function loadStatus() {
  try {
    const s = await api("GET", "/api/status");
    state.activeWorkspace = s.workspace?.path || "";
    state.drafts = new Set(s.drafts.sections || []);
    const g = s.git;
    const drafts = s.drafts.count
      ? `${s.drafts.count} — ${s.drafts.sections.join(", ")}`
      : "none";
    const site = s.site_url
      ? `<span class="pill">${link(s.site_url, s.site_url)}</span>`
      : `<span class="pill warn">site URL unknown</span>`;
    const pills = [
      `<span class="pill workspace" title="${esc(s.workspace?.path || "")}">workspace: ${esc(s.workspace?.title || "unknown")}</span>`,
      `<span class="pill">version ${esc(s.version)}</span>`,
      `<span class="pill ${s.drafts.count ? "warn" : ""}">drafts: ${esc(drafts)}</span>`,
      `<span class="pill ${g.clean ? "ok" : "warn"}">${g.clean ? "working tree clean" : "uncommitted changes"}</span>`,
      g.in_sync === null
        ? `<span class="pill warn">github: unknown</span>`
        : `<span class="pill ${g.in_sync ? "ok" : "warn"}">${g.in_sync ? "in sync with origin/main" : `out of sync (ahead ${g.ahead}, behind ${g.behind})`}</span>`,
      `<span class="pill">${esc(g.branch)} @ ${esc(g.head)}</span>`,
      site,
    ];
    $("status").innerHTML = pills.join("");
    $("app-title").innerHTML = `${esc(s.site)} <span class="tag">admin</span>`;
    $("app-workspace").textContent = s.workspace?.path || "";
    document.title = `${s.site} — Admin`;
    renderSections();
  } catch (error) {
    state.activeWorkspace = "";
    $("status").innerHTML = `<span class="pill warn">status error: ${esc(error.message)}</span>`;
    $("app-workspace").textContent = "";
  }
}

// ---------------------------------------------------------------- workspaces

function workspaceById(path) {
  return state.workspaces.find((workspace) => workspace.path === path) || null;
}

function workspaceMeta(workspace) {
  const bits = [workspace.version];
  if (workspace.branch || workspace.head) bits.push(`${workspace.branch || "?"} @ ${workspace.head || "?"}`);
  if (workspace.drafts) bits.push(`${workspace.drafts} draft${workspace.drafts === 1 ? "" : "s"}`);
  return bits.filter(Boolean).join(" · ");
}

async function loadWorkspaces() {
  try {
    const data = await api("GET", "/api/workspaces");
    state.workspaces = data.workspaces || [];
    state.activeWorkspace = data.active || "";
    state.suggested = data.suggested || null;
    renderWorkspaces();
    applySuggestedCreateDefaults();
  } catch (error) {
    $("ws-current").textContent = `could not load workspaces: ${error.message}`;
    $("ws-list").textContent = "";
  }
}

function renderWorkspaces() {
  const current = workspaceById(state.activeWorkspace);
  const currentBox = $("ws-current");
  if (!current) {
    currentBox.innerHTML = `<div class="ws-title">No workspace selected</div>
      <div class="ws-path">Use “Switch workspace” or create one below.</div>`;
  } else {
    const meta = workspaceMeta(current);
    const site = current.site_url ? `<span>${link(current.site_url, "open site")}</span>` : `<span class="muted">no site URL</span>`;
    const repo = current.repo_url ? `<span>${link(current.repo_url, "open repo")}</span>` : `<span class="muted">no repo URL</span>`;
    const problem = current.error
      ? `<div class="pill warn">${esc(current.error)}</div>`
      : `<div class="pill ${current.clean ? "ok" : "warn"}">${current.clean ? "working tree clean" : "uncommitted changes"}</div>`;
    currentBox.innerHTML = `
      <div class="ws-title">${esc(current.title)} <span class="badge">active</span></div>
      <div class="ws-path">${esc(current.path)}</div>
      <div class="ws-meta">
        <span class="pill">${esc(meta || "no git metadata")}</span>
        ${problem}
        ${site}
        ${repo}
      </div>`;
  }

  const list = $("ws-list");
  list.innerHTML = "";
  if (!state.workspaces.length) {
    list.innerHTML = `<div class="muted">No known rule workspaces. Create one below.</div>`;
  }
  for (const workspace of state.workspaces) {
    const isActive = workspace.path === state.activeWorkspace;
    const item = document.createElement("div");
    item.className = `ws-item${isActive ? " active" : ""}`;
    const actions = isActive
      ? `<span class="badge">active</span>`
      : `<button class="secondary ws-action" data-switch="${esc(workspace.path)}" ${workspace.valid ? "" : "disabled"}>Switch</button>`;
    item.innerHTML = `
      <div class="ws-item-main">
        <div class="ws-item-title">${esc(workspace.title)}${isActive ? "" : ""}</div>
        <span class="ws-item-path">${esc(workspace.path)}</span>
        <span class="ws-item-meta">${esc(workspace.valid ? workspaceMeta(workspace) : (workspace.error || "invalid workspace"))}</span>
      </div>
      <div class="ws-item-actions">${actions}</div>`;
    list.appendChild(item);
  }
  list.querySelectorAll("[data-switch]").forEach((button) => {
    button.addEventListener("click", () => switchWorkspace(button.dataset.switch));
  });

  const source = $("ws-create-source");
  const previous = source.value;
  source.innerHTML = "";
  for (const workspace of state.workspaces.filter((item) => item.valid)) {
    const option = document.createElement("option");
    option.value = workspace.path;
    option.textContent = `${workspace.title} — ${workspace.path}`;
    source.appendChild(option);
  }
  if ([...source.options].some((option) => option.value === previous)) source.value = previous;
  else if (state.activeWorkspace) source.value = state.activeWorkspace;

  const forget = $("ws-forget-list");
  forget.innerHTML = "";
  const removable = state.workspaces.filter((workspace) => workspace.path !== state.activeWorkspace);
  if (!removable.length) {
    forget.innerHTML = `<div class="muted">Nothing else in the list.</div>`;
  }
  for (const workspace of removable) {
    const item = document.createElement("div");
    item.className = "ws-item";
    item.innerHTML = `
      <div class="ws-item-main">
        <div class="ws-item-title">${esc(workspace.title)}</div>
        <span class="ws-item-path">${esc(workspace.path)}</span>
      </div>
      <div class="ws-item-actions">
        <button class="secondary ws-action" data-forget="${esc(workspace.path)}">Remove</button>
      </div>`;
    forget.appendChild(item);
  }
  forget.querySelectorAll("[data-forget]").forEach((button) => {
    button.addEventListener("click", () => forgetWorkspace(button.dataset.forget));
  });
  setBusy(state.busy, null);
}

function applySuggestedCreateDefaults() {
  if (!state.suggested) return;
  const path = $("ws-create-path");
  const title = $("ws-create-title");
  const year = $("ws-create-year");
  if (!path.dataset.touched) path.value = state.suggested.path;
  if (!title.dataset.touched) title.value = state.suggested.title;
  if (!year.dataset.touched) year.value = state.suggested.year;
}

function resetEditor() {
  state.current = null;
  state.content = "";
  state.drafts = new Set();
  $("editor").value = "";
  $("editor-title").textContent = "Select a section";
  $("editor-path").textContent = "";
  $("editor-hint").textContent = "";
  $("draft-banner").classList.add("hidden");
  $("btn-save").disabled = true;
  renderSections();
}

async function refreshWorkspaceData() {
  await Promise.all([loadWorkspaces(), loadStatus(), loadSections()]);
  try { await loadDiff(); } catch { /* diff is non-fatal */ }
  setBusy(false);
}

function hasUnsavedEdits() {
  return Boolean(state.current && $("editor").value !== state.content);
}

async function switchWorkspace(path) {
  if (state.busy) return;
  if (hasUnsavedEdits() && !confirm("Discard unsaved edits in the editor?")) return;
  setBusy(true, "switching workspace…");
  try {
    const result = await api("POST", "/api/workspaces/select", { path });
    state.activeWorkspace = result.workspace.path;
    resetEditor();
    closeWorkspaces();
    toast(`Now working on ${result.workspace.title}`);
    await refreshWorkspaceData();
  } catch (error) {
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
}

async function addExistingWorkspace(event) {
  event.preventDefault();
  if (state.busy) return;
  const input = $("ws-add-path");
  const path = input.value.trim();
  if (!path) return;
  await switchWorkspace(path);
  input.value = "";
}

async function createWorkspace(event) {
  event.preventDefault();
  if (state.busy) return;
  const path = $("ws-create-path").value.trim();
  if (!path) {
    toast("Choose a directory for the new workspace.", "warn");
    return;
  }
  const mode = $("ws-create-mode").value;
  const yearText = $("ws-create-year").value.trim();
  if (yearText && (!/^\d{4}$/.test(yearText) || Number(yearText) < 2000 || Number(yearText) > 2100)) {
    toast("Year must be a whole number between 2000 and 2100.", "warn");
    return;
  }
  const body = {
    path,
    mode,
    source_path: mode === "copy" ? $("ws-create-source").value : null,
    title: $("ws-create-title").dataset.touched ? $("ws-create-title").value.trim() || null : null,
    year: yearText ? Number(yearText) : null,
    repo_url: $("ws-create-repo").value.trim() || null,
    git_init: $("ws-create-git").checked,
    activate: true,
  };
  if (mode === "copy" && !body.source_path) {
    toast("Choose a workspace to copy from.", "warn");
    return;
  }
  setBusy(true, "creating workspace…");
  $("ws-create-hint").textContent = "creating files, git repo and first commit…";
  try {
    const result = await api("POST", "/api/workspaces/create", body);
    resetEditor();
    closeWorkspaces();
    if (result.warnings?.length) {
      toast(`Created ${result.workspace.title}, but: ${result.warnings.join(" ")}`, "warn");
    } else {
      toast(`Created ${result.workspace.title}`);
    }
    await refreshWorkspaceData();
  } catch (error) {
    toast(error.message, "warn");
    $("ws-create-hint").textContent = error.message;
  } finally {
    setBusy(false);
  }
}

async function forgetWorkspace(path) {
  if (state.busy) return;
  if (!confirm("Remove this directory from the workspace list? Files are not deleted.")) return;
  try {
    await api("POST", "/api/workspaces/forget", { path });
    toast("Removed from the workspace list.");
    await loadWorkspaces();
  } catch (error) {
    toast(error.message, "warn");
  }
}

// ---------------------------------------------------------------- sections

async function loadSections() {
  try {
    const data = await api("GET", "/api/sections");
    state.sections = data.sections;
    renderSections();
  } catch (error) {
    state.sections = [];
    $("sections").innerHTML = `<li class="muted">could not load sections: ${esc(error.message)}</li>`;
  }
}

function renderSections() {
  const list = $("sections");
  list.innerHTML = "";
  for (const section of state.sections) {
    const item = document.createElement("li");
    item.dataset.id = section.id;
    if (state.current && section.id === state.current.id) item.classList.add("active");
    const dot = state.drafts.has(section.id) ? '<span class="dot" title="draft saved">●</span> ' : "";
    item.innerHTML = `<span class="s-title">${dot}${esc(section.title)}</span>
                      <span class="s-path">${esc(section.path)}</span>`;
    item.addEventListener("click", () => selectSection(section));
    list.appendChild(item);
  }
}

async function selectSection(section) {
  if (state.busy) return;
  if (hasUnsavedEdits() && !confirm("Discard unsaved edits in the editor?")) return;

  state.current = section;
  state.content = section.content;
  $("editor").value = section.content;
  $("editor-title").textContent = section.title;
  $("editor-path").textContent = `docs/${section.path}`;
  $("btn-save").disabled = false;
  $("editor-hint").textContent = "";
  $("draft-banner").classList.toggle("hidden", !state.drafts.has(section.id));
  renderSections();
}

// ---------------------------------------------------------------- drafts

async function saveDraft() {
  if (!state.current || state.busy) return;
  const content = $("editor").value;
  if (!content.trim()) {
    $("editor-hint").textContent = "refusing to save an empty draft";
    return;
  }
  try {
    const result = await api("PUT", `/api/draft/${encodeURIComponent(state.current.id)}`, { content });
    state.content = content;
    state.drafts.add(state.current.id);
    $("draft-banner").classList.remove("hidden");
    $("editor-hint").textContent = `draft saved (${result.bytes} bytes)`;
    renderSections();
    await loadStatus();
  } catch (error) {
    $("editor-hint").textContent = error.message;
  }
}

// ---------------------------------------------------------------- diff

async function loadDiff() {
  try {
    const data = await api("GET", "/api/diff");
    const changed = data.entries.filter((entry) => entry.changed);
    state.drafts = new Set(changed.map((entry) => entry.section));
    renderSections();
    const pre = $("diff");
    pre.innerHTML = "";
    if (!changed.length) {
      pre.textContent = "No drafts — the working copy matches the published rulebook.";
    } else {
      for (const entry of changed) {
        for (const line of entry.diff.replace(/\n$/, "").split("\n")) {
          const span = document.createElement("span");
          let cls = "meta";
          if (line.startsWith("+++") || line.startsWith("---")) cls = "meta";
          else if (line.startsWith("@@")) cls = "hunk";
          else if (line.startsWith("+")) cls = "add";
          else if (line.startsWith("-")) cls = "del";
          span.className = cls;
          span.textContent = line + "\n";
          pre.appendChild(span);
        }
      }
    }
    setBusy(state.busy, null);
  } catch (error) {
    $("diff").textContent = "diff error: " + error.message;
  }
}

// ---------------------------------------------------------------- pipeline

function showLog(lines) {
  const pre = $("log");
  pre.innerHTML = "";
  for (const line of lines) {
    const span = document.createElement("span");
    span.className = line.cls || "";
    span.textContent = line.text + "\n";
    pre.appendChild(span);
  }
  switchTab("log");
}

function stepsToLines(result) {
  const lines = (result.steps || []).map((step) => ({
    text: `[${step.ok ? "ok" : "FAIL"}] ${step.step}: ${step.detail}`,
    cls: step.ok ? "step-ok" : "step-fail",
  }));
  if (result.ok) {
    lines.push({ text: "", cls: "" });
    if (result.previous_version) lines.push({ text: `published ${result.previous_version} -> ${result.version}`, cls: "" });
    else lines.push({ text: `rolled back to ${result.version}`, cls: "" });
    lines.push({ text: `commit  ${result.commit}`, cls: "" });
    if (result.site_url) lines.push({ text: `live    ${result.site_url}`, cls: "" });
  } else {
    lines.push({ text: "", cls: "" });
    lines.push({ text: `error: ${result.error}`, cls: "step-fail" });
  }
  return lines;
}

async function publish() {
  if (state.busy) return;
  if (!confirm("Publish the saved drafts to the live public site for this workspace?")) return;
  setBusy(true);
  showLog([{ text: "publishing — validating, building, committing and deploying (can take a few minutes)…", cls: "meta" }]);
  try {
    const result = await api("POST", "/api/publish");
    showLog(stepsToLines(result));
    await loadDiff();
    await loadStatus();
    await loadSections();
  } catch (error) {
    showLog([{ text: "publish failed: " + error.message, cls: "step-fail" }]);
  } finally {
    setBusy(false);
  }
}

async function rollback() {
  if (state.busy) return;
  if (!confirm("Roll the live site back to the previous published version for this workspace?")) return;
  setBusy(true);
  showLog([{ text: "rolling back — reverting, building and deploying…", cls: "meta" }]);
  try {
    const result = await api("POST", "/api/rollback");
    showLog(stepsToLines(result));
    await loadStatus();
    await loadSections();
  } catch (error) {
    showLog([{ text: "rollback failed: " + error.message, cls: "step-fail" }]);
  } finally {
    setBusy(false);
  }
}

// ---------------------------------------------------------------- ui plumbing

function switchTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
  for (const panel of ["editor", "diff", "log"]) {
    $(`tab-${panel}`).classList.toggle("hidden", panel !== name);
  }
  if (name === "diff") loadDiff();
}

function openWorkspaces() {
  $("workspace-modal").classList.remove("hidden");
  loadWorkspaces();
}

function closeWorkspaces() {
  $("workspace-modal").classList.add("hidden");
}

$("btn-theme").addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "light" ? "dark" : "light");
});
$("btn-workspaces").addEventListener("click", openWorkspaces);
$("btn-close-workspaces").addEventListener("click", closeWorkspaces);
$("workspace-modal").addEventListener("click", (event) => {
  if (event.target === $("workspace-modal")) closeWorkspaces();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("workspace-modal").classList.contains("hidden")) closeWorkspaces();
});

$("ws-create-mode").addEventListener("change", () => {
  $("ws-source-wrap").classList.toggle("hidden", $("ws-create-mode").value !== "copy");
});
$("ws-create-path").addEventListener("input", (event) => { event.target.dataset.touched = "1"; });
$("ws-create-title").addEventListener("input", (event) => { event.target.dataset.touched = "1"; });
$("ws-create-year").addEventListener("input", (event) => {
  event.target.dataset.touched = "1";
  const title = $("ws-create-title");
  if (!title.dataset.touched && /^\d{4}$/.test(event.target.value)) {
    title.value = `Fred Lobster Race Rules ${event.target.value}`;
  }
});
$("ws-add-form").addEventListener("submit", addExistingWorkspace);
$("ws-create-form").addEventListener("submit", createWorkspace);

document.querySelectorAll(".tab").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

$("btn-save").addEventListener("click", saveDraft);
$("btn-publish").addEventListener("click", publish);
$("btn-rollback").addEventListener("click", rollback);
$("btn-refresh-diff").addEventListener("click", loadDiff);

$("editor").addEventListener("input", () => {
  if (!state.current) return;
  const changed = $("editor").value !== state.content;
  $("editor-hint").textContent = changed ? "unsaved edits — click Save draft" : "";
});

(async function init() {
  initTheme();
  await refreshWorkspaceData();
})();
