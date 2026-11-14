"use strict";

const $ = (id) => document.getElementById(id);
const THEME_KEY = "fred-admin-theme";
const state = {
  sections: [],
  archived: [],
  selectedSections: new Set(),
  pendingPublish: null,
  recoveryRequired: false,
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
  const operationPending = Boolean(state.pendingPublish) || state.recoveryRequired;
  $("btn-publish").disabled = on || !state.drafts.size || state.pendingPublish?.action === "rollback" || state.recoveryRequired;
  $("btn-rollback").disabled = on || state.pendingPublish?.action === "publish" || state.recoveryRequired;
  $("btn-workspaces").disabled = on;
  $("btn-save").disabled = on || !state.current || operationPending;
  $("editor").readOnly = operationPending;
  $("btn-recovery-restore").disabled = on || !state.recoveryRequired;
  ["btn-add-section", "btn-copy-sections", "btn-archive-sections", "btn-move-up", "btn-move-down"].forEach((id) => {
    $(id).disabled = on || operationPending || $(id).dataset.unavailable === "1";
  });
  document.querySelectorAll(".ws-action").forEach((button) => { button.disabled = on; });
  document.querySelectorAll("#archived-sections button, #sections input[type=checkbox]").forEach((button) => {
    button.disabled = on || operationPending;
  });
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
    state.pendingPublish = s.pending_publish || null;
    state.recoveryRequired = Boolean(s.recovery_required);
    $("recovery-banner").classList.toggle("hidden", !state.recoveryRequired);
    if (state.pendingPublish) {
      const action = state.pendingPublish.action === "rollback" ? "rollback" : "publish";
      $("editor-hint").textContent = `editing is paused until the pending ${action} retry finishes`;
    }
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
    setBusy(state.busy, null);
  } catch (error) {
    state.activeWorkspace = "";
    state.recoveryRequired = false;
    $("recovery-banner").classList.add("hidden");
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
  if (hasUnsavedEdits() && !confirm("Discard unsaved edits in the editor before creating a workspace?")) return;
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
    state.sections = data.sections || [];
    state.archived = data.archived || [];
    const activeIds = new Set(state.sections.map((section) => section.id));
    state.selectedSections = new Set([...state.selectedSections].filter((id) => activeIds.has(id)));
    if (state.current && !activeIds.has(state.current.id)) {
      state.current = null;
      state.content = "";
      $("editor").value = "";
      $("editor-title").textContent = "Select a section";
      $("editor-path").textContent = "";
      $("editor-hint").textContent = "";
      $("btn-save").disabled = true;
      $("draft-banner").classList.add("hidden");
    } else if (state.current) {
      state.current = state.sections.find((section) => section.id === state.current.id) || state.current;
    }
    renderSections();
  } catch (error) {
    state.sections = [];
    state.archived = [];
    $("sections").innerHTML = `<li class="muted">could not load sections: ${esc(error.message)}</li>`;
    renderArchivedSections();
  }
}

function renderSections() {
  const list = $("sections");
  list.innerHTML = "";
  const query = $("section-search").value.trim().toLocaleLowerCase();
  const filter = $("section-filter").value;
  const visible = state.sections.filter((section) => {
    const matchesSearch = `${section.title} ${section.path}`.toLocaleLowerCase().includes(query);
    return matchesSearch && (filter !== "drafts" || state.drafts.has(section.id));
  });
  for (const section of visible) {
    const item = document.createElement("li");
    if (state.current && section.id === state.current.id) item.classList.add("active");
    const checkLabel = document.createElement("label");
    checkLabel.className = "section-check";
    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.checked = state.selectedSections.has(section.id);
    checkbox.setAttribute("aria-label", `Select ${section.title}`);
    checkbox.addEventListener("change", () => {
      if (checkbox.checked) state.selectedSections.add(section.id);
      else state.selectedSections.delete(section.id);
      updateSelectionControls();
    });
    checkLabel.appendChild(checkbox);
    const open = document.createElement("button");
    open.type = "button";
    open.className = "section-open";
    open.setAttribute("aria-current", state.current?.id === section.id ? "page" : "false");
    const title = document.createElement("span");
    title.className = "s-title";
    if (state.drafts.has(section.id)) {
      const dot = document.createElement("span");
      dot.className = "dot";
      dot.title = "draft saved";
      dot.textContent = "● ";
      title.appendChild(dot);
    }
    title.appendChild(document.createTextNode(section.title));
    const path = document.createElement("span");
    path.className = "s-path";
    path.textContent = section.path;
    open.append(title, path);
    open.addEventListener("click", () => selectSection(section));
    item.append(checkLabel, open);
    list.appendChild(item);
  }
  if (!visible.length) {
    const empty = document.createElement("li");
    empty.className = "muted section-empty";
    empty.textContent = state.sections.length ? "No sections match this search/filter." : "No active sections.";
    list.appendChild(empty);
  }
  renderArchivedSections();
  updateSelectionControls();
}

function renderArchivedSections() {
  const list = $("archived-sections");
  list.innerHTML = "";
  $("archive-count").textContent = state.archived.length ? `(${state.archived.length})` : "(none)";
  if (!state.archived.length) {
    const empty = document.createElement("li");
    empty.className = "muted";
    empty.textContent = "No archived sections.";
    list.appendChild(empty);
  }
  for (const section of state.archived) {
    const item = document.createElement("li");
    const main = document.createElement("div");
    main.className = "archived-main";
    const title = document.createElement("strong");
    title.textContent = section.title;
    const path = document.createElement("span");
    path.className = "s-path";
    path.textContent = section.path;
    main.append(title, path);
    const actions = document.createElement("div");
    actions.className = "archive-actions";
    const restore = document.createElement("button");
    restore.type = "button";
    restore.className = "secondary";
    restore.textContent = "Restore";
    restore.setAttribute("aria-label", `Restore ${section.title}`);
    restore.disabled = state.busy || Boolean(state.pendingPublish) || state.recoveryRequired;
    restore.addEventListener("click", () => restoreSections([section.id]));
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Delete permanently";
    remove.setAttribute("aria-label", `Permanently delete ${section.title}`);
    remove.disabled = state.busy || Boolean(state.pendingPublish) || state.recoveryRequired;
    remove.addEventListener("click", () => permanentlyDeleteSections([section.id]));
    actions.append(restore, remove);
    item.append(main, actions);
    list.appendChild(item);
  }
}

function updateSelectionControls() {
  const count = state.selectedSections.size;
  $("selection-count").textContent = `${count} selected`;
  $("btn-copy-sections").dataset.unavailable = count ? "0" : "1";
  $("btn-archive-sections").dataset.unavailable = count ? "0" : "1";
  const selectedIndexes = state.sections
    .map((section, index) => state.selectedSections.has(section.id) ? index : -1)
    .filter((index) => index >= 0);
  const firstSelected = selectedIndexes[0] ?? -1;
  const lastSelected = selectedIndexes.at(-1) ?? -1;
  $("btn-move-up").dataset.unavailable = firstSelected > 0 ? "0" : "1";
  $("btn-move-down").dataset.unavailable = lastSelected >= 0 && lastSelected < state.sections.length - 1 ? "0" : "1";
  const unavailable = state.busy || Boolean(state.pendingPublish) || state.recoveryRequired;
  for (const id of ["btn-copy-sections", "btn-archive-sections", "btn-move-up", "btn-move-down"]) {
    $(id).disabled = unavailable || $(id).dataset.unavailable === "1";
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
  $("btn-save").disabled = state.busy || Boolean(state.pendingPublish) || state.recoveryRequired;
  $("editor-hint").textContent = "";
  $("draft-banner").classList.toggle("hidden", !state.drafts.has(section.id));
  renderSections();
  if (window.matchMedia("(max-width: 900px)").matches) {
    $("section-sidebar").classList.remove("mobile-open");
    $("btn-toggle-sections").setAttribute("aria-expanded", "false");
  }
}

// ---------------------------------------------------------- section structure

function canLeaveEditor() {
  return !hasUnsavedEdits() || confirm("Discard unsaved edits in the editor?");
}

async function refreshAfterStructure() {
  await loadSections();
  await loadDiff();
  await loadStatus();
}

function openSectionModal() {
  const source = $("new-section-source");
  source.innerHTML = '<option value="">Start with blank content</option>';
  for (const section of state.sections) {
    const option = document.createElement("option");
    option.value = section.id;
    option.textContent = `${section.title} — ${section.path}`;
    source.appendChild(option);
  }
  $("section-form").reset();
  $("section-form-hint").textContent = "";
  $("section-modal").classList.remove("hidden");
  $("new-section-title").focus();
}

function closeSectionModal() {
  $("section-modal").classList.add("hidden");
}

async function createSection(event) {
  event.preventDefault();
  if (state.busy || !canLeaveEditor()) return;
  const title = $("new-section-title").value.trim();
  const path = $("new-section-path").value.trim();
  if (!title || !path) return;
  const body = { title, path };
  const content = $("new-section-content").value;
  const copyFrom = $("new-section-source").value;
  if (copyFrom) body.copy_from = copyFrom;
  else if (content) body.content = content;
  setBusy(true, "creating section draft…");
  $("section-form-hint").textContent = "Saving a structural draft…";
  try {
    await api("POST", "/api/sections", body);
    closeSectionModal();
    toast("Section created as a draft. Nothing was published.");
    await refreshAfterStructure();
  } catch (error) {
    $("section-form-hint").textContent = error.message;
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
}

function sectionSlug(path) {
  const parts = path.split("/");
  const filename = parts.pop().replace(/\.md$/i, "");
  const slug = filename.toLocaleLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "section";
  return [...parts, slug].filter(Boolean).join("/");
}

function openCopyModal() {
  if (!canLeaveEditor()) return;
  const selected = state.sections.filter((section) => state.selectedSections.has(section.id));
  if (!selected.length) return;
  const usedPaths = new Set([...state.sections, ...state.archived].map((section) => section.path.toLocaleLowerCase()));
  const rows = $("copy-rows");
  rows.innerHTML = "";
  for (const section of selected) {
    const base = sectionSlug(section.path);
    let copyPath = `${base}-copy.md`;
    let suffix = 2;
    while (usedPaths.has(copyPath.toLocaleLowerCase())) copyPath = `${base}-copy-${suffix++}.md`;
    usedPaths.add(copyPath.toLocaleLowerCase());
    const row = document.createElement("fieldset");
    row.className = "copy-row";
    row.dataset.sourceId = section.id;
    const legend = document.createElement("legend");
    legend.textContent = `Copy of ${section.title}`;
    const titleLabel = document.createElement("label");
    titleLabel.textContent = "New title";
    const titleInput = document.createElement("input");
    titleInput.required = true;
    titleInput.maxLength = 160;
    titleInput.value = `Copy of ${section.title}`;
    titleLabel.appendChild(titleInput);
    const pathLabel = document.createElement("label");
    pathLabel.textContent = "New path";
    const pathInput = document.createElement("input");
    pathInput.required = true;
    pathInput.value = copyPath;
    pathInput.spellcheck = false;
    pathLabel.appendChild(pathInput);
    row.append(legend, titleLabel, pathLabel);
    rows.appendChild(row);
  }
  $("copy-form-hint").textContent = "";
  $("copy-modal").classList.remove("hidden");
  rows.querySelector("input")?.focus();
}

function closeCopyModal() {
  $("copy-modal").classList.add("hidden");
}

async function createSelectedCopies(event) {
  event.preventDefault();
  if (state.busy) return;
  const rows = [...$("copy-rows").querySelectorAll(".copy-row")];
  if (!rows.length) return;
  setBusy(true, "copying sections…");
  let created = 0;
  let failure = null;
  try {
    for (const row of rows) {
      const [titleInput, pathInput] = row.querySelectorAll("input");
      const title = titleInput.value.trim();
      const path = pathInput.value.trim();
      if (!title || !path) throw new Error("Each copy needs a title and path.");
      await api("POST", "/api/sections", { title, path, copy_from: row.dataset.sourceId });
      created += 1;
    }
    closeCopyModal();
    toast(`${created} section${created === 1 ? "" : "s"} copied as drafts. Nothing was published.`);
  } catch (error) {
    failure = error;
    $("copy-form-hint").textContent = created ? `${created} copy/copies created; ${error.message}` : error.message;
    toast(created ? `Created ${created} copy/copies; remaining copies failed: ${error.message}` : error.message, "warn");
  } finally {
    if (created) await refreshAfterStructure();
    setBusy(false);
  }
  if (failure) return;
}

async function archiveSelectedSections() {
  if (state.busy || !canLeaveEditor()) return;
  const ids = [...state.selectedSections];
  if (!ids.length) return;
  const names = state.sections.filter((section) => ids.includes(section.id)).map((section) => section.title);
  if (!confirm(`Archive ${names.length} section${names.length === 1 ? "" : "s"}? They can be restored later. This saves a structural draft; nothing is published.`)) return;
  setBusy(true, "archiving sections…");
  try {
    await api("POST", "/api/sections/archive", { ids });
    state.selectedSections.clear();
    toast("Sections archived as a draft. Nothing was published.");
    await refreshAfterStructure();
  } catch (error) {
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
}

async function restoreSections(ids) {
  if (state.busy || !canLeaveEditor()) return;
  const names = state.archived.filter((section) => ids.includes(section.id)).map((section) => section.title);
  if (!confirm(`Restore ${names.join(", ") || "selected archived section(s)"} as active section${ids.length === 1 ? "" : "s"}? This saves a structural draft; nothing is published.`)) return;
  setBusy(true, "restoring sections…");
  try {
    await api("POST", "/api/sections/restore", { ids });
    toast("Sections restored as a draft. Nothing was published.");
    await refreshAfterStructure();
  } catch (error) {
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
}

async function permanentlyDeleteSections(ids) {
  if (state.busy || !canLeaveEditor()) return;
  const names = state.archived.filter((section) => ids.includes(section.id)).map((section) => section.title);
  const label = names.join(", ") || "selected archived section(s)";
  if (!confirm(`Permanently delete ${label}? This is not archive and cannot be undone.`)) return;
  if (prompt(`To permanently delete ${label}, type DELETE.`) !== "DELETE") {
    toast("Permanent deletion cancelled.", "warn");
    return;
  }
  setBusy(true, "deleting archived sections…");
  try {
    await api("DELETE", "/api/sections", { ids });
    toast("Archived sections permanently deleted. Nothing was published.");
    await refreshAfterStructure();
  } catch (error) {
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
}

async function moveSelectedSection(direction) {
  if (state.busy || !canLeaveEditor() || !state.selectedSections.size) return;
  const ids = state.sections.map((section) => section.id);
  let moved = false;
  if (direction < 0) {
    for (let index = 1; index < ids.length; index += 1) {
      if (state.selectedSections.has(ids[index]) && !state.selectedSections.has(ids[index - 1])) {
        [ids[index - 1], ids[index]] = [ids[index], ids[index - 1]];
        moved = true;
      }
    }
  } else {
    for (let index = ids.length - 2; index >= 0; index -= 1) {
      if (state.selectedSections.has(ids[index]) && !state.selectedSections.has(ids[index + 1])) {
        [ids[index], ids[index + 1]] = [ids[index + 1], ids[index]];
        moved = true;
      }
    }
  }
  if (!moved) return;
  setBusy(true, "saving section order…");
  try {
    await api("PUT", "/api/sections/order", { ids });
    toast("Section order saved as a draft. Nothing was published.");
    await refreshAfterStructure();
  } catch (error) {
    toast(error.message, "warn");
  } finally {
    setBusy(false);
  }
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
    const entries = data.entries || [];
    const changed = entries.filter((entry) => entry.changed);
    state.drafts = new Set(changed.map((entry) => entry.section));
    if (data.structure?.changed) state.drafts.add("navigation");
    state.pendingPublish = data.pending_publish || null;
    if (state.pendingPublish) {
      state.drafts.add(state.pendingPublish.action === "rollback" ? "rollback-retry" : "publish-retry");
    }
    renderSections();
    const pre = $("diff");
    pre.innerHTML = "";
    const structure = data.structure_summary ?? data.structure;
    const structureChanged = typeof structure === "object"
      ? Boolean(structure?.changed)
      : Boolean(structure);
    if (structureChanged) {
      const summary = document.createElement("span");
      summary.className = "structure-summary";
      const text = Array.isArray(structure?.summary)
        ? structure.summary.join("\n")
        : typeof structure === "string" ? structure : JSON.stringify(structure, null, 2);
      summary.textContent = `Structure changes\n${text}\n\n`;
      pre.appendChild(summary);
    }
    if (state.pendingPublish) {
      const pending = document.createElement("span");
      pending.className = "structure-summary";
      const action = state.pendingPublish.action === "rollback" ? "Rollback" : "Publish";
      pending.textContent = `${action} retry pending\nCommit ${state.pendingPublish.commit} · version ${state.pendingPublish.version}\nUse ${action} to retry push and live verification.\n\n`;
      pre.appendChild(pending);
    }
    if (!changed.length && !structureChanged && !state.pendingPublish) {
      pre.textContent = "No drafts — the working copy matches the published rulebook.";
    }
    for (const entry of changed) {
      for (const line of String(entry.diff || "").replace(/\n$/, "").split("\n")) {
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
  if (state.pendingPublish?.action === "rollback") return;
  const message = state.pendingPublish
    ? `Retry pushing publish commit ${state.pendingPublish.commit} and verify the live site?`
    : "Publish the saved drafts to the live public site for this workspace?";
  if (!confirm(message)) return;
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
  if (state.pendingPublish?.action === "publish") return;
  const message = state.pendingPublish?.action === "rollback"
    ? `Retry pushing rollback commit ${state.pendingPublish.commit} and verify the live site?`
    : "Roll the live site back to the previous published version for this workspace?";
  if (!confirm(message)) return;
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

async function restoreInterruptedPublish() {
  if (state.busy || !state.recoveryRequired) return;
  const answer = prompt("This restores the saved pre-publish files and discards later edits to those rulebook files. Type RESTORE to continue.");
  if (answer !== "RESTORE") return;
  setBusy(true, "restoring interrupted publish staging…");
  try {
    const result = await api("POST", "/api/recovery/restore", { confirm: "RESTORE" });
    toast(result.detail || "Pre-publish files restored.");
    await refreshWorkspaceData();
  } catch (error) {
    toast(error.message, "warn");
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
$("btn-add-section").addEventListener("click", openSectionModal);
$("btn-close-section-modal").addEventListener("click", closeSectionModal);
$("btn-close-copy-modal").addEventListener("click", closeCopyModal);
$("section-modal").addEventListener("click", (event) => {
  if (event.target === $("section-modal")) closeSectionModal();
});
$("copy-modal").addEventListener("click", (event) => {
  if (event.target === $("copy-modal")) closeCopyModal();
});
$("section-form").addEventListener("submit", createSection);
$("copy-form").addEventListener("submit", createSelectedCopies);
$("section-search").addEventListener("input", renderSections);
$("section-filter").addEventListener("change", renderSections);
$("btn-copy-sections").addEventListener("click", openCopyModal);
$("btn-archive-sections").addEventListener("click", archiveSelectedSections);
$("btn-move-up").addEventListener("click", () => moveSelectedSection(-1));
$("btn-move-down").addEventListener("click", () => moveSelectedSection(1));
$("btn-toggle-sections").addEventListener("click", () => {
  const open = $("section-sidebar").classList.toggle("mobile-open");
  $("btn-toggle-sections").setAttribute("aria-expanded", String(open));
});
$("workspace-modal").addEventListener("click", (event) => {
  if (event.target === $("workspace-modal")) closeWorkspaces();
});
document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!$("workspace-modal").classList.contains("hidden")) closeWorkspaces();
  if (!$("section-modal").classList.contains("hidden")) closeSectionModal();
  if (!$("copy-modal").classList.contains("hidden")) closeCopyModal();
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

document.querySelectorAll(".tab[data-tab]").forEach((tab) => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

$("btn-save").addEventListener("click", saveDraft);
$("btn-publish").addEventListener("click", publish);
$("btn-rollback").addEventListener("click", rollback);
$("btn-refresh-diff").addEventListener("click", loadDiff);
$("btn-recovery-restore").addEventListener("click", restoreInterruptedPublish);

$("editor").addEventListener("input", () => {
  if (!state.current) return;
  const changed = $("editor").value !== state.content;
  $("editor-hint").textContent = changed ? "unsaved edits — click Save draft" : "";
});

(async function init() {
  initTheme();
  await refreshWorkspaceData();
})();
