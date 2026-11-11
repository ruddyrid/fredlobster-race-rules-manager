"use strict";

const $ = (id) => document.getElementById(id);
const state = { sections: [], current: null, content: "", drafts: new Set(), busy: false };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
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
    throw new Error(data.detail || `${method} ${path} failed (HTTP ${response.status})`);
  }
  return data;
}

function setBusy(on, label) {
  state.busy = on;
  $("btn-publish").disabled = on || !state.drafts.size;
  $("btn-rollback").disabled = on;
  $("btn-save").disabled = on || !state.current;
  if (label) $("status").insertAdjacentHTML("afterbegin", `<span class="pill">${esc(label)}</span>`);
}

// ---------------------------------------------------------------- status

async function loadStatus() {
  try {
    const s = await api("GET", "/api/status");
    const g = s.git;
    const drafts = s.drafts.count
      ? `${s.drafts.count} — ${s.drafts.sections.join(", ")}`
      : "none";
    const pills = [
      `<span class="pill">version ${esc(s.version)}</span>`,
      `<span class="pill ${s.drafts.count ? "warn" : ""}">drafts: ${esc(drafts)}</span>`,
      `<span class="pill ${g.clean ? "ok" : "warn"}">${g.clean ? "working tree clean" : "uncommitted changes"}</span>`,
      g.in_sync === null
        ? `<span class="pill warn">github: unknown</span>`
        : `<span class="pill ${g.in_sync ? "ok" : "warn"}">${g.in_sync ? "in sync with origin/main" : `out of sync (ahead ${g.ahead}, behind ${g.behind})`}</span>`,
      `<span class="pill">${esc(g.branch)} @ ${esc(g.head)}</span>`,
      `<span class="pill">${esc(s.site_url)}</span>`,
    ];
    $("status").innerHTML = pills.join("");
  } catch (error) {
    $("status").innerHTML = `<span class="pill warn">status error: ${esc(error.message)}</span>`;
  }
}

// ---------------------------------------------------------------- sections

async function loadSections() {
  try {
    const data = await api("GET", "/api/sections");
    state.sections = data.sections;
    renderSections();
  } catch (error) {
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
  const hasEdits = state.current && $("editor").value !== state.content;
  if (hasEdits && !confirm("Discard unsaved edits in the editor?")) return;

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
    $("btn-publish").disabled = state.busy || !changed.length;
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
  if (!confirm("Publish the saved drafts to the live public site?")) return;
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
  if (!confirm("Roll the live site back to the previous published version?")) return;
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
  await Promise.all([loadStatus(), loadSections()]);
  try { await loadDiff(); } catch { /* diff is non-fatal */ }
  setBusy(false);
})();
