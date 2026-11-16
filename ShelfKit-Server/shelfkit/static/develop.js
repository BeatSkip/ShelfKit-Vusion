"use strict";

/* The Develop screen and Settings › AI services. Loaded after app.js (uses $, stored,
 * store, ageText, showSettingsTab).
 *
 * Develop is AI-first: a prompt bar on top sends a request to the AI service picked in
 * Settings, with the app's files, the virtual tag's data and the app's log as context.
 * The server's agent job (/api/dev/agent) answers with a plan and complete new files.
 * Nothing is written until Accept; the proposal's layout is drawn on the virtual tag
 * first, and its app.py is only compiled. Below the agent: the code editor (Save and
 * reload checkpoints first), the checkpoints, and a debug view. On the right: the
 * virtual tag FFF0, which runs the app's own callbacks in the server but is never bound
 * and never sent anything.
 */
(function () {
  const AGENT_POLL_MS = 900;
  const D = {
    apps: [],                   // /api/inkapps apps
    app: stored("dev.app", ""),
    files: [],                  // [{name, text}] as saved
    edits: {},                  // name -> unsaved text
    file: "",                   // the file in the editor
    tab: stored("dev.tab", "code"),
    vt: null,                   // last /api/dev/virtual answer
    pretend: "",                // "" = now, else "YYYY-MM-DDTHH:MM"
    draft: null,                // {png, diagnostics, label}: an unsaved layout drawn
    showProposal: true,         // the glass shows the agent's proposal when there is one
    job: null,                  // the agent job being shown
    jobs: [],                   // earlier asks, this server run
    ai: null,                   // /api/dev/agent/history .ai: {label, model} or {error}
    checkpoints: [],
    log: [],
    diff: false,
    busy: false,
    msg: null,
    poll: 0,
    layoutSeq: 0,
  };
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = encodeURIComponent;

  async function api(path, body) {
    const opts = body === undefined ? {} :
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  const appOf = (id) => D.apps.find((a) => a.id === id);
  const dirtyNames = () => Object.keys(D.edits).filter((n) => D.edits[n] !== textOf(n, true));
  function textOf(name, saved) {
    if (!saved && name in D.edits) return D.edits[name];
    const f = D.files.find((x) => x.name === name);
    return f ? f.text : "";
  }

  // ── loading ──────────────────────────────────────────────────────────────
  async function loadApps() {
    const r = await api("/api/inkapps");
    D.apps = r.apps.filter((a) => !a.disabled);
    if (!appOf(D.app)) D.app = D.apps[0] ? D.apps[0].id : "";
  }

  async function openApp(id) {
    if (id !== D.app && dirtyNames().length &&
        !confirm(`Leave ${dirtyNames().join(", ")} unsaved? The changes are lost.`)) {
      $("dev-app").value = D.app;
      return;
    }
    D.app = id;
    store("dev.app", id);
    D.edits = {};
    D.file = "";
    D.job = null;
    D.draft = null;
    D.diff = false;
    D.msg = null;
    await loadApp();
  }

  async function loadApp() {
    renderHead();
    if (!D.app) { renderAll(); return; }
    const app = D.app;
    const [files, cps, hist, log] = await Promise.all([
      api(`/api/dev/files?app=${enc(app)}`).catch((e) => ({ files: [], error: e.message })),
      api(`/api/dev/checkpoints?app=${enc(app)}`).catch(() => ({ checkpoints: [] })),
      api(`/api/dev/agent/history?app=${enc(app)}`).catch(() => ({ jobs: [], ai: null })),
      api(`/api/inkapps/log?app=${enc(app)}`).catch(() => ({ log: [] })),
    ]);
    if (app !== D.app) return;
    D.files = files.files || [];
    if (!D.file || !D.files.some((f) => f.name === D.file)) {
      D.file = (D.files.find((f) => f.name === "layout.xml") || D.files[0] || {}).name || "";
    }
    D.checkpoints = cps.checkpoints || [];
    D.jobs = hist.jobs || [];
    D.ai = hist.ai;
    D.log = log.log || log.lines || [];
    if (!D.job && D.jobs.length) {
      const last = D.jobs[D.jobs.length - 1];
      try { D.job = await api(`/api/dev/agent?job=${enc(last.id)}`); } catch { D.job = null; }
      if (D.job && D.job.status === "running") pollJob();
    }
    renderAll();
    virtual("draw");
  }

  async function refreshSide() {
    const app = D.app;
    const [cps, log] = await Promise.all([
      api(`/api/dev/checkpoints?app=${enc(app)}`).catch(() => ({ checkpoints: [] })),
      api(`/api/inkapps/log?app=${enc(app)}`).catch(() => ({ log: [] })),
    ]);
    if (app !== D.app) return;
    D.checkpoints = cps.checkpoints || [];
    D.log = log.log || log.lines || [];
    if (D.tab !== "code") renderPane();
  }

  // ── the head ─────────────────────────────────────────────────────────────
  function renderHead() {
    const pick = $("dev-app");
    const shape = D.apps.map((a) => a.id + a.title).join("|");
    if (pick.dataset.shape !== shape) {
      pick.innerHTML = D.apps.map((a) => `<option value="${esc(a.id)}">${esc(a.title || a.id)}</option>`).join("")
        || "<option value=\"\">No apps yet</option>";
      pick.dataset.shape = shape;
    }
    pick.value = D.app;
    const dirty = dirtyNames();
    $("dev-dirty").textContent = dirty.length
      ? `${dirty.length} unsaved file${dirty.length > 1 ? "s" : ""}: ${dirty.join(", ")}` : "";
    $("dev-save").disabled = !dirty.length || D.busy;
    $("dev-discard").disabled = !dirty.length || D.busy;
    const a = appOf(D.app);
    $("dev-app-error").textContent = a && a.error ? `Didn't load: ${a.error}` : "";
    $("dev-app-error").hidden = !(a && a.error);
  }

  function renderAll() {
    renderHead();
    renderPrompt();
    renderAgent();
    renderTabs();
    renderPane();
    renderVirtual();
  }

  // ── the prompt bar ───────────────────────────────────────────────────────
  function renderPrompt() {
    const who = D.ai;
    const el = $("dev-ai");
    if (!who || who.error) {
      const why = who && who.error ? who.error.replace(/: add .*$/, "") : "No AI service set up";
      el.innerHTML = `${esc(why.charAt(0).toUpperCase() + why.slice(1))}.
        <a href="#settings" data-ai-settings>Set one up</a>`;
    } else {
      el.innerHTML = `${esc(who.label)} · <code>${esc(who.model)}</code> ·
        <a href="#settings" data-ai-settings>change</a>`;
    }
    const running = D.job && D.job.status === "running";
    $("dev-send").disabled = running || !D.app;
    $("dev-send").textContent = running ? "Working…" : "Send";
    const dirty = dirtyNames();
    $("dev-sees").innerHTML = ["the app's files" + (dirty.length ? " (as saved)" : ""),
      "the virtual tag's data", "the app's log", "the InkLayout reference"]
      .map((x) => `<span class="dev-pill">${esc(x)}</span>`).join("");
  }

  async function send(prompt) {
    prompt = (prompt ?? $("dev-ask").value).trim();
    if (!prompt || !D.app) return;
    if (dirtyNames().length && !confirm("You have unsaved edits. The AI works from the saved files, " +
        "and accepting its change would replace your edits. Send anyway?")) return;
    try {
      const r = await api("/api/dev/agent", { app: D.app, prompt,
        context: { file: D.file, tab: D.tab, pretend: D.pretend || null } });
      $("dev-ask").value = "";
      if (D.job) D.jobs.push({ id: D.job.id, prompt: D.job.prompt, status: D.job.status, summary: D.job.summary });
      D.job = { id: r.job, prompt, status: "running", steps: [], app: D.app };
      D.showProposal = true;
      D.diff = false;
      renderPrompt();
      renderAgent();
      pollJob();
    } catch (e) {
      D.job = { id: "", prompt, status: "error", steps: [{ title: "Not sent", detail: e.message, state: "error" }] };
      renderAgent();
    }
  }

  function pollJob() {
    clearTimeout(D.poll);
    D.poll = setTimeout(async () => {
      if (!D.job || !D.job.id) return;
      try {
        const view = await api(`/api/dev/agent?job=${enc(D.job.id)}`);
        if (!D.job || view.id !== D.job.id) return;
        const was = D.job.status;
        D.job = view;
        renderAgent();
        renderPrompt();
        if (view.status === "running") pollJob();
        else if (was === "running") renderVirtual();
      } catch (e) {
        D.job.status = "error";
        D.job.steps = [...(D.job.steps || []), { title: "Lost the job", detail: e.message, state: "error" }];
        renderAgent();
        renderPrompt();
      }
    }, AGENT_POLL_MS);
  }

  // ── the agent feed ───────────────────────────────────────────────────────
  const STEP_ICON = {
    done: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    running: '<span class="dev-spin" aria-hidden="true"></span>',
    error: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M4.5 4.5l7 7M11.5 4.5l-7 7" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round"/></svg>',
    question: '<svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M6 6a2 2 0 1 1 2.6 1.9c-.4.2-.6.5-.6 1V10M8 12.4v.1" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"/></svg>',
  };

  function renderAgent() {
    const box = $("dev-agent");
    const j = D.job;
    const older = D.jobs.filter((x) => !j || x.id !== j.id).slice(-5);
    if (!j) {
      box.innerHTML = `<div class="dev-empty">
        <p><strong>Ask for what you want on the tag.</strong> The AI reads this app's files and
          proposes complete new ones. You see the change drawn on the virtual tag before
          anything is saved.</p>
        <div class="dev-try">${["Make the most important number much bigger",
          "Add a phone button that undoes the last change", "Show when the data was last updated"]
          .map((t) => `<button type="button" class="app-chip" data-try="${esc(t)}">${esc(t)}</button>`).join("")}</div>
      </div>`;
      return;
    }
    const steps = (j.steps || []).map((s) => {
      if (s.change && j.proposal) return changeCard(j, s);
      return `<li class="dev-step is-${esc(s.state)}"><span class="dev-step-ico">${STEP_ICON[s.state] || STEP_ICON.done}</span>
        <span class="dev-step-text"><span class="dev-step-title">${esc(s.title)}</span>
        ${s.detail ? `<span class="dev-step-detail">${esc(s.detail)}</span>` : ""}</span></li>`;
    }).join("");
    const waiting = j.status === "running" && !(j.steps || []).some((s) => s.state === "running")
      ? `<li class="dev-step is-running"><span class="dev-step-ico">${STEP_ICON.running}</span>
         <span class="dev-step-text"><span class="dev-step-title">Starting</span></span></li>` : "";
    const answers = j.status === "question" && (j.answers || []).length
      ? `<div class="dev-answers">${j.answers.map((a) =>
        `<button type="button" class="app-chip" data-try="${esc(a)}">${esc(a)}</button>`).join("")}
        <span class="hint">or type an answer above</span></div>` : "";
    const next = (j.suggestions || []).length && j.status !== "running"
      ? `<div class="dev-next"><span class="dev-next-label">Try next</span>${j.suggestions.map((t) =>
        `<button type="button" class="app-chip" data-try="${esc(t)}">${esc(t)}</button>`).join("")}</div>` : "";
    const state = { running: "Working", proposed: "Waiting for you", question: "Needs your input",
      accepted: "Accepted", rejected: "Rejected", done: "Done", error: "Stopped" }[j.status] || j.status;
    box.innerHTML = `
      <div class="dev-agent-head">
        <h2>Agent</h2>
        <span class="pill ${j.status === "error" ? "bad" : j.status === "accepted" ? "ok" : ""}">${esc(state)}</span>
        <span class="dev-agent-meta">${j.seconds != null ? `${j.seconds} s` : ""}</span>
        <button type="button" data-forget title="The AI forgets this conversation; the files stay">New conversation</button>
      </div>
      ${older.length ? `<details class="dev-older"><summary>${older.length} earlier request${older.length > 1 ? "s" : ""}</summary>
        <ul>${older.map((o) => `<li><span class="dev-older-status">${esc(o.status)}</span> ${esc(o.prompt)}
          ${o.summary ? `<span class="hint">— ${esc(o.summary)}</span>` : ""}</li>`).join("")}</ul></details>` : ""}
      <div class="dev-ask-bubble">${esc(j.prompt)}</div>
      ${j.summary ? `<p class="dev-summary">${esc(j.summary)}</p>` : ""}
      <ol class="dev-steps">${steps}${waiting}</ol>
      ${answers}${next}`;
  }

  function changeCard(j, step) {
    const p = j.proposal;
    const open = j.status === "proposed";
    const stats = p.stats.map((s) => `<span class="dev-stat"><code>${esc(s.name)}</code>${s.new ? " new" : ""}
      <span class="dev-add">+${s.added}</span> <span class="dev-del">−${s.removed}</span></span>`).join("");
    const diff = D.diff ? `<div class="dev-diff">${p.stats.map((s) =>
      `<div class="dev-diff-file"><div class="dev-diff-name">${esc(s.name)}</div>${diffHtml(p.before[s.name] || "", p.files[s.name])}</div>`).join("")}</div>` : "";
    return `<li class="dev-step dev-change ${p.broken ? "is-broken" : ""}">
      <div class="dev-change-head">
        <span class="dev-change-title">${p.broken ? "Proposed change, with problems" : "Proposed change"}</span>
        ${stats}
      </div>
      <p class="dev-change-note">${open ? "Not saved. The virtual tag shows it; accept to write the files (a checkpoint is saved first)."
        : j.status === "accepted" ? "Accepted and saved." : "Rejected: the files did not change."}</p>
      <div class="dev-change-actions">
        <button type="button" data-diff aria-pressed="${D.diff}">${D.diff ? "Hide diff" : "Show diff"}</button>
        ${open ? `<button type="button" data-take title="Put the proposed files in the editor as unsaved edits">Edit first</button>
        <span class="spacer"></span>
        <button type="button" data-reject>Reject</button>
        <button type="button" class="primary" data-accept>${p.broken ? "Accept anyway" : "Accept"}</button>` : ""}
      </div>
      ${diff}
    </li>`;
  }

  // a line diff (longest common subsequence), enough for app-sized files
  function diffHtml(a, b) {
    const x = a.split("\n"), y = b.split("\n");
    if (x.length * y.length > 4e6) return '<p class="hint">Too large to compare here.</p>';
    const n = x.length, m = y.length;
    const t = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let k = m - 1; k >= 0; k--) {
      t[i][k] = x[i] === y[k] ? t[i + 1][k + 1] + 1 : Math.max(t[i + 1][k], t[i][k + 1]);
    }
    const out = [];
    let i = 0, k = 0;
    while (i < n || k < m) {
      if (i < n && k < m && x[i] === y[k]) { out.push([" ", x[i]]); i++; k++; }
      else if (i < n && (k >= m || t[i + 1][k] >= t[i][k + 1])) { out.push(["-", x[i]]); i++; }
      else { out.push(["+", y[k]]); k++; }
    }
    // only changed lines with two lines of context
    const keep = out.map((_, idx) => out.slice(Math.max(0, idx - 2), idx + 3).some((l) => l[0] !== " "));
    let html = "", gap = false;
    out.forEach((l, idx) => {
      if (!keep[idx]) { if (!gap) html += '<div class="dev-dl dev-gap">⋯</div>'; gap = true; return; }
      gap = false;
      const cls = l[0] === "+" ? "dev-dl-add" : l[0] === "-" ? "dev-dl-del" : "";
      html += `<div class="dev-dl ${cls}"><span class="dev-dl-sign">${l[0]}</span>${esc(l[1]) || " "}</div>`;
    });
    return `<pre class="dev-diff-body">${html}</pre>`;
  }

  async function accept() {
    if (!D.job) return;
    D.busy = true;
    try {
      const r = await api("/api/dev/agent/apply", { job: D.job.id });
      D.job.status = "accepted";
      D.edits = {};
      D.msg = r.error ? { text: `Saved, but the app didn't load: ${r.error}`, bad: true }
        : { text: "Saved and reloaded. A checkpoint of the old files is under Versions." };
      await loadApps();
      await loadApp();
    } catch (e) {
      D.msg = { text: e.message, bad: true };
    }
    D.busy = false;
    renderAll();
  }

  async function reject() {
    if (!D.job) return;
    try { await api("/api/dev/agent/reject", { job: D.job.id }); D.job.status = "rejected"; }
    catch (e) { D.msg = { text: e.message, bad: true }; }
    renderAgent();
    renderVirtual();
  }

  function takeProposal() {
    const p = D.job && D.job.proposal;
    if (!p) return;
    for (const [name, text] of Object.entries(p.files)) {
      if (!D.files.some((f) => f.name === name)) D.files.push({ name, text: "" });
      D.edits[name] = text;
    }
    D.file = p.stats[0].name;
    D.tab = "code";
    D.showProposal = false;
    renderAll();
    layoutDraft();
  }

  // ── tabs: code, versions, debug ──────────────────────────────────────────
  function renderTabs() {
    for (const b of document.querySelectorAll("#dev-tabs [data-tab]")) {
      b.setAttribute("aria-selected", String(b.dataset.tab === D.tab));
    }
  }

  function renderPane() {
    const pane = $("dev-pane");
    const msg = D.msg ? `<p class="dev-msg ${D.msg.bad ? "bad" : ""}" role="status">${esc(D.msg.text)}</p>` : "";
    if (!D.app) {
      pane.innerHTML = '<p class="hint">No apps yet. Make one with New app on the Apps screen.</p>';
      return;
    }
    if (D.tab === "versions") pane.innerHTML = msg + versionsHtml();
    else if (D.tab === "debug") pane.innerHTML = msg + debugHtml();
    else {
      pane.innerHTML = msg + codeHtml();
      const ed = $("dev-editor");
      if (ed) ed.value = textOf(D.file);
    }
  }

  function codeHtml() {
    const dirty = new Set(dirtyNames());
    const tabs = D.files.map((f) => `<button type="button" role="tab" data-file="${esc(f.name)}"
      aria-selected="${f.name === D.file}">${esc(f.name)}${dirty.has(f.name) ? '<span class="dev-dot" title="Unsaved"></span>' : ""}</button>`).join("");
    const isLayout = D.file.endsWith(".xml");
    const note = isLayout
      ? "Drawn on the virtual tag as you type (not saved). InkLayout: 152 × 296, black, white, red."
      : D.file.endsWith(".py") ? "Runs inside the server only after Save and reload; a checkpoint is saved first."
        : "Saved with the app.";
    const diags = isLayout && D.draft && D.draft.diagnostics ? diagHtml(D.draft.diagnostics) : "";
    return `
      <div class="dev-files" role="tablist" aria-label="Files">${tabs}</div>
      <textarea id="dev-editor" class="dev-editor" spellcheck="false" autocomplete="off"
        aria-label="${esc(D.file)}"></textarea>
      <p class="hint">${note}</p>
      ${diags}`;
  }

  function diagHtml(list) {
    const shown = list.filter((d) => d.level !== "info");
    if (!shown.length) return '<p class="dev-diag-ok">No layout problems.</p>';
    return `<ul class="dev-diags">${shown.map((d) => `<li class="is-${esc(d.level)}"><span>${esc(d.level)}</span>
      <code>${esc(d.at)}</code> ${esc(d.msg)}</li>`).join("")}</ul>`;
  }

  function versionsHtml() {
    const a = appOf(D.app) || {};
    const rows = D.checkpoints.map((c) => `<li>
      <span class="dev-cp-when">${esc(new Date(c.at * 1000).toLocaleString())}</span>
      ${c.label ? `<span class="pill">${esc(c.label)}</span>` : ""}
      <span class="dev-cp-note">${esc(c.note)}</span>
      <span class="dev-cp-files">${esc((c.files || []).join(", "))}</span>
      <button type="button" data-revert="${esc(c.id)}">Go back to this</button></li>`).join("");
    return `
      <div class="dev-about">
        <h3>${esc(a.title || D.app)}</h3>
        <p class="hint">${esc(a.description || "No description.")} · folder <code>inkapps/${esc(D.app)}</code></p>
      </div>
      <h3>Checkpoints</h3>
      <p class="hint">Every save, accepted AI change and revert keeps a copy of the files from just
        before it, in the app's data folder (the last 40).</p>
      ${rows ? `<ol class="dev-cps">${rows}</ol>` : '<p class="hint">None yet: the first save makes one.</p>'}`;
  }

  function debugHtml() {
    const vt = D.vt || {};
    const log = D.log.slice(-80).map((l) => {
      const [at, line] = Array.isArray(l) ? l : [null, l];
      return `${at ? new Date(at * 1000).toLocaleTimeString() + "  " : ""}${line}`;
    }).join("\n");
    return `
      <div class="dev-debug">
        <section>
          <h3>Virtual tag</h3>
          <dl class="dev-facts">
            <dt>Last draw</dt><dd>${vt.ms != null ? `${vt.ms} ms` : "—"}</dd>
            <dt>Time it drew for</dt><dd>${esc(vt.now || "—")}</dd>
            <dt>Result</dt><dd>${vt.error ? `<span class="dev-bad">${esc(vt.error)}</span>` : vt.png ? "drawn" : "—"}</dd>
          </dl>
          ${vt.diagnostics ? diagHtml(vt.diagnostics) : ""}
          <h4>What the layout gets (@app.data)</h4>
          <pre class="json">${esc(JSON.stringify(vt.data ?? {}, null, 1))}</pre>
          <h4>tag.data</h4>
          <pre class="json">${esc(JSON.stringify(vt.state ?? {}, null, 1))}</pre>
        </section>
        <section>
          <div class="dev-log-head"><h3>The app's log</h3><button type="button" data-relog>Refresh</button></div>
          <pre class="json dev-log">${esc(log || "Nothing logged yet.")}</pre>
        </section>
      </div>`;
  }

  async function saveFiles() {
    const names = dirtyNames();
    if (!names.length) return;
    D.busy = true;
    renderHead();
    try {
      const files = Object.fromEntries(names.map((n) => [n, D.edits[n]]));
      const r = await api("/api/dev/save", { app: D.app, files });
      D.edits = {};
      D.draft = null;
      D.msg = r.error ? { text: `Saved, but the app didn't load: ${r.error}`, bad: true }
        : { text: `Saved ${names.join(", ")} and reloaded the app.` };
      await loadApps();
      await loadApp();
    } catch (e) {
      D.msg = { text: e.message, bad: true };
      renderPane();
    }
    D.busy = false;
    renderHead();
  }

  async function revert(id) {
    if (!confirm("Put the app's files back as they were at this checkpoint? Your current files are kept as a checkpoint too.")) return;
    try {
      const r = await api("/api/dev/revert", { app: D.app, id });
      D.edits = {};
      D.msg = r.error ? { text: `Reverted, but the app didn't load: ${r.error}`, bad: true } : { text: "Reverted and reloaded." };
      await loadApps();
      await loadApp();
    } catch (e) {
      D.msg = { text: e.message, bad: true };
      renderPane();
    }
  }

  // a layout being edited: drawn with the virtual tag's data, not saved
  let draftTimer = 0;
  function layoutDraft() {
    clearTimeout(draftTimer);
    draftTimer = setTimeout(async () => {
      const name = D.file.endsWith(".xml") ? D.file : "layout.xml";
      if (!(name in D.edits) || D.edits[name] === textOf(name, true)) {
        D.draft = null;
        renderVirtual();
        return;
      }
      const seq = ++D.layoutSeq;
      try {
        const r = await api("/api/layout/render", { layout: D.edits[name], data: (D.vt && D.vt.data) || {} });
        if (seq !== D.layoutSeq) return;
        D.draft = { png: r.png, diagnostics: r.diagnostics };
      } catch (e) {
        D.draft = { png: null, diagnostics: [{ level: "error", at: name, msg: e.message }] };
      }
      renderVirtual();
      const box = document.querySelector("#dev-pane .dev-diags, #dev-pane .dev-diag-ok");
      const html = D.draft ? diagHtml(D.draft.diagnostics || []) : "";
      if (box) box.outerHTML = html;
      else if (html && D.tab === "code") $("dev-pane").insertAdjacentHTML("beforeend", html);
    }, 300);
  }

  // ── the virtual tag ──────────────────────────────────────────────────────
  async function virtual(what, extra = {}) {
    if (!D.app) return;
    const app = D.app;
    try {
      const r = await api("/api/dev/virtual", { app, do: what, now: D.pretend || null, ...extra });
      if (app !== D.app) return;
      D.vt = r;
    } catch (e) {
      D.vt = { error: e.message };
    }
    renderVirtual();
    if (D.tab === "debug") renderPane();
    if (what !== "draw") refreshSide();
  }

  function renderVirtual() {
    const box = $("dev-virtual");
    const a = appOf(D.app);
    if (!a) { box.innerHTML = ""; return; }
    const vt = D.vt || {};
    const prop = D.job && D.job.status === "proposed" && D.job.preview;
    let src = vt.png, cap = "Saved app · nothing is sent to a tag";
    if (prop && D.showProposal) { src = D.job.preview; cap = "The AI's proposal · not saved"; }
    else if (D.draft && D.draft.png) { src = D.draft.png; cap = "Your unsaved layout"; }
    const k = Number(stored("dev.scale", "2")) === 1 ? 1 : 2;
    const controls = (a.controls || []).map((c) => c.kind === "text"
      ? `<form class="dev-ctl" data-ctl="${esc(c.id)}"><input name="v" placeholder="${esc(c.placeholder || c.label)}"
          aria-label="${esc(c.label)}"><button type="submit">${esc(c.label)}</button></form>`
      : `<button type="button" data-ctl="${esc(c.id)}">${esc(c.label)}</button>`).join("");
    const fields = (a.config_fields || []).map((f) => `<label>${esc(f.label)}
      <input name="${esc(f.key)}" value="${esc((vt.config || {})[f.key] ?? f.default)}"></label>`).join("");
    box.innerHTML = `
      <div class="app-glass-head">
        <span class="app-glass-title">Virtual tag <code>FFF0</code></span>
        <span class="apps-seg" role="group" aria-label="Preview size">
          <button type="button" data-vscale="1" aria-pressed="${k === 1}">1×</button>
          <button type="button" data-vscale="2" aria-pressed="${k === 2}">2×</button>
        </span>
      </div>
      ${prop ? `<span class="apps-seg dev-which" role="group" aria-label="Show">
        <button type="button" data-which="now" aria-pressed="${!D.showProposal}">Now</button>
        <button type="button" data-which="prop" aria-pressed="${D.showProposal}">Proposal</button></span>` : ""}
      <span class="tag-case" style="--glass-w: ${152 * k}px; --glass-h: ${296 * k}px"><span class="glass">${src
    ? `<img src="data:image/png;base64,${src}" alt="The virtual tag's screen">`
    : `<span class="dev-glass-err">${esc(vt.error || "Drawing…")}</span>`}</span></span>
      <span class="app-glass-cap">${esc(cap)}${vt.ms != null && src === vt.png ? ` · ${vt.ms} ms` : ""}</span>
      ${vt.error && src ? `<p class="dev-bad dev-vt-err">${esc(vt.error)}</p>` : ""}
      <div class="dev-vt-group">
        <label class="dev-pretend">Pretend it is
          <input type="datetime-local" id="dev-pretend" value="${esc(D.pretend)}"></label>
        ${D.pretend ? '<button type="button" data-now>Now</button>' : ""}
      </div>
      <div class="app-glass-actions">
        <button type="button" data-vt="draw">Draw again</button>
        ${(a.timers || []).length ? `<button type="button" data-vt="timers" title="Runs every @app.every timer once">Run timers</button>` : ""}
        ${a.has_on_open ? '<button type="button" data-vt="open" title="Runs what an NFC tap runs">Simulate NFC tap</button>' : ""}
      </div>
      ${controls ? `<div class="dev-vt-group dev-vt-col"><span class="dev-vt-label">Phone page</span>${controls}</div>` : ""}
      ${fields ? `<form class="dev-vt-group dev-vt-col dev-vt-config" id="dev-config"><span class="dev-vt-label">Settings for this tag</span>
        ${fields}<button type="submit">Use these settings</button></form>` : ""}
      <button type="button" class="dev-vt-reset" data-vt="reset" title="Forget the virtual tag's data and settings">Reset the virtual tag</button>`;
  }

  // ── events ───────────────────────────────────────────────────────────────
  function wire() {
    $("dev-app").addEventListener("change", (e) => openApp(e.target.value));
    $("dev-save").addEventListener("click", saveFiles);
    $("dev-discard").addEventListener("click", () => {
      if (!confirm("Throw away the unsaved changes?")) return;
      D.edits = {};
      D.draft = null;
      renderAll();
    });
    $("dev-prompt").addEventListener("submit", (e) => { e.preventDefault(); send(); });
    $("dev-ask").addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); send(); }
    });
    document.addEventListener("keydown", (e) => {
      if (screenIs("develop") && e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        $("dev-ask").focus();
      }
    });
    $("dev-tabs").addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (!b) return;
      D.tab = b.dataset.tab;
      store("dev.tab", D.tab);
      renderTabs();
      renderPane();
      if (D.tab !== "code") refreshSide();
    });

    const screenEl = document.querySelector('.screen[data-screen="develop"]');
    screenEl.addEventListener("click", (e) => {
      const b = e.target.closest("button, a");
      if (!b) return;
      if (b.matches("[data-ai-settings]")) { e.preventDefault(); openAiSettings(); }
      else if (b.dataset.try) { send(b.dataset.try); }
      else if (b.matches("[data-forget]")) {
        api("/api/dev/agent/forget", { app: D.app }).catch(() => {});
        if (D.job) D.jobs.push({ id: D.job.id, prompt: D.job.prompt, status: D.job.status, summary: D.job.summary });
        D.job = null;
        renderAgent();
      }
      else if (b.matches("[data-diff]")) { D.diff = !D.diff; renderAgent(); }
      else if (b.matches("[data-accept]")) accept();
      else if (b.matches("[data-reject]")) reject();
      else if (b.matches("[data-take]")) takeProposal();
      else if (b.dataset.file) { D.file = b.dataset.file; renderPane(); layoutDraft(); }
      else if (b.dataset.revert) revert(b.dataset.revert);
      else if (b.matches("[data-relog]")) refreshSide();
      else if (b.dataset.vt) {
        if (b.dataset.vt === "reset" && !confirm("Forget the virtual tag's data and settings?")) return;
        virtual(b.dataset.vt);
      }
      else if (b.dataset.which) { D.showProposal = b.dataset.which === "prop"; renderVirtual(); }
      else if (b.dataset.vscale) { store("dev.scale", b.dataset.vscale); renderVirtual(); }
      else if (b.matches("[data-now]")) { D.pretend = ""; virtual("draw"); }
      else if (b.dataset.ctl && b.tagName === "BUTTON" && !b.closest("form")) virtual("action", { action: b.dataset.ctl });
    });
    screenEl.addEventListener("submit", (e) => {
      const f = e.target;
      if (f.matches(".dev-ctl")) {
        e.preventDefault();
        virtual("action", { action: f.dataset.ctl, value: f.elements.v.value });
      } else if (f.id === "dev-config") {
        e.preventDefault();
        const config = {};
        for (const input of f.querySelectorAll("input[name]")) config[input.name] = input.value;
        virtual("config", { config });
      }
    });
    screenEl.addEventListener("change", (e) => {
      if (e.target.id === "dev-pretend") { D.pretend = e.target.value; virtual("draw"); }
    });
    screenEl.addEventListener("input", (e) => {
      if (e.target.id !== "dev-editor") return;
      D.edits[D.file] = e.target.value;
      const wasDirty = $("dev-save").disabled;
      renderHead();
      if (wasDirty !== $("dev-save").disabled || !document.querySelector(`[data-file="${CSS.escape(D.file)}"] .dev-dot`)) {
        const tab = document.querySelector(`[data-file="${CSS.escape(D.file)}"]`);
        const dirty = D.edits[D.file] !== textOf(D.file, true);
        if (tab && dirty && !tab.querySelector(".dev-dot")) tab.insertAdjacentHTML("beforeend", '<span class="dev-dot" title="Unsaved"></span>');
        if (tab && !dirty) tab.querySelector(".dev-dot")?.remove();
      }
      if (D.file.endsWith(".xml")) layoutDraft();
    });
    screenEl.addEventListener("keydown", (e) => {
      if (e.target.id === "dev-editor" && e.key === "Tab" && !e.shiftKey) {
        e.preventDefault();
        document.execCommand("insertText", false, "    ");
      } else if (e.target.id === "dev-editor" && e.key === "s" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        saveFiles();
      }
    });
    window.addEventListener("beforeunload", (e) => {
      if (dirtyNames().length) { e.preventDefault(); e.returnValue = ""; }
    });
  }

  const screenIs = (name) => {
    const el = document.querySelector(`.screen[data-screen="${name}"]`);
    return el && !el.hidden;
  };

  function openAiSettings() {
    location.hash = "#settings";
    if (typeof showSettingsTab === "function") showSettingsTab("ai");
  }

  window.developShown = async () => {
    try {
      await loadApps();
      await loadApp();
    } catch (e) {
      $("dev-agent").innerHTML = `<p class="dev-bad">${esc(e.message)}</p>`;
    }
  };
  window.openDevelop = (app) => {
    if (app && app !== D.app) {
      D.app = app;
      store("dev.app", app);
      D.edits = {};
      D.file = "";
      D.job = null;
      D.draft = null;
    }
    location.hash = "#develop";
  };

  // ── Settings › AI services ───────────────────────────────────────────────
  const AI = { data: null, note: {} };

  window.aiSettingsShown = async () => {
    try {
      AI.data = await api("/api/ai");
    } catch (e) {
      $("ai-accounts").innerHTML = `<p class="dev-bad">${esc(e.message)}</p>`;
      return;
    }
    renderAi();
  };

  function renderAi() {
    const d = AI.data;
    $("ai-accounts").innerHTML = d.providers.map((p) => {
      const note = AI.note[p.id];
      const status = !p.sdk_ok ? ["bad", `Needs pip install ${p.sdk}`]
        : !p.has_key ? ["", "Not set up"]
          : p.check && !p.check.ok ? ["bad", "Last test failed"]
            : !p.enabled ? ["", "Off"]
              : p.check && p.check.ok ? ["ok", "Works"] : ["ok", "Key saved"];
      return `<form class="ai-card" data-provider="${esc(p.id)}" autocomplete="off">
        <div class="ai-card-head">
          <h3>${esc(p.label)}</h3>
          <span class="pill ${status[0]}">${esc(status[1])}</span>
          <span class="spacer"></span>
          <label class="ai-default" title="The service the Develop screen's agent uses">
            <input type="radio" name="ai-default" value="${esc(p.id)}" ${d.default === p.id ? "checked" : ""}
              ${p.has_key && p.enabled ? "" : "disabled"}> Use for Develop</label>
        </div>
        <div class="setting-fields">
          <label>API key
            <input name="api_key" type="password" spellcheck="false"
              placeholder="${p.has_key ? `saved, ends ${esc(p.key_hint)}: paste to replace` : "paste the key"}"></label>
          <label>Model
            <input name="model" list="ai-models-${esc(p.id)}" value="${esc(p.model)}" placeholder="${esc(p.default_model)}">
            <datalist id="ai-models-${esc(p.id)}">${(AI.note[p.id + ":models"] || p.models).map((m) =>
              `<option value="${esc(m)}">`).join("")}</datalist></label>
          <label>Base URL (optional)
            <input name="base_url" value="${esc(p.base_url)}" placeholder="${esc(p.default_base_url || "the official API")}"></label>
        </div>
        <label class="ai-enabled"><input type="checkbox" name="enabled" ${p.enabled ? "checked" : ""}> Enabled</label>
        <div class="row ai-actions">
          <button type="submit" class="primary">Save</button>
          <button type="button" data-ai="check" ${p.has_key ? "" : "disabled"}>Test the key</button>
          <button type="button" data-ai="models" ${p.has_key ? "" : "disabled"}>Load models</button>
          ${p.has_key ? '<button type="button" data-ai="forget">Remove the key</button>' : ""}
          <a href="${esc(p.keys_url)}" target="_blank" rel="noopener noreferrer">Get a key ↗</a>
        </div>
        <p class="hint ai-note ${note && note.bad ? "dev-bad" : ""}" role="status">${esc(note ? note.text
          : p.check ? `${p.check.text}${p.checked_at ? ` (${new Date(p.checked_at * 1000).toLocaleString()})` : ""}` : "")}</p>
      </form>`;
    }).join("");
    $("ai-tokens").innerHTML = `
      ${d.tokens.length ? `<ul class="ai-token-list">${d.tokens.map((t) => `<li>
        <code>${esc(t.name)}</code><span class="ai-token-hint">${esc(t.hint)}</span>
        <span class="hint">${esc(t.note || "")}</span><span class="spacer"></span>
        <button type="button" data-token-remove="${esc(t.name)}">Remove</button></li>`).join("")}</ul>`
        : '<p class="hint">No tokens yet.</p>'}
      <form class="setting-fields ai-token-add" id="ai-token-form" autocomplete="off">
        <label>Name<input name="name" placeholder="weather_key" spellcheck="false"></label>
        <label>Value<input name="value" type="password" spellcheck="false" placeholder="paste the token"></label>
        <label>Note<input name="note" placeholder="what it is for"></label>
        <button type="submit">Add token</button>
      </form>
      <p class="hint" id="ai-token-note" role="status">${esc(AI.note.token || "")}</p>`;
  }

  function wireAi() {
    const root = document.querySelector('section[data-tab="ai"]');
    root.addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.target;
      if (f.id === "ai-token-form") {
        try {
          const r = await api("/api/ai/token", { name: f.elements.name.value, value: f.elements.value.value,
            note: f.elements.note.value });
          AI.data.tokens = r.tokens;
          AI.note.token = `Saved. An app reads it with tag.token("${f.elements.name.value.trim()}").`;
        } catch (err) { AI.note.token = err.message; }
        renderAi();
        return;
      }
      const id = f.dataset.provider;
      const body = { provider: id, model: f.elements.model.value, base_url: f.elements.base_url.value,
        enabled: f.elements.enabled.checked };
      if (f.elements.api_key.value) body.api_key = f.elements.api_key.value;
      try {
        AI.data = await api("/api/ai/account", body);
        AI.note[id] = { text: body.api_key ? "Saved. Test the key to be sure it works." : "Saved." };
      } catch (err) { AI.note[id] = { text: err.message, bad: true }; }
      renderAi();
    });
    root.addEventListener("change", async (e) => {
      if (e.target.name !== "ai-default") return;
      try { AI.data = await api("/api/ai/default", { provider: e.target.value }); } catch { /* shown on reload */ }
      renderAi();
    });
    root.addEventListener("click", async (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      if (b.dataset.tokenRemove) {
        if (!confirm(`Remove the token ${b.dataset.tokenRemove}? Apps that use it stop getting it.`)) return;
        try { AI.data.tokens = (await api("/api/ai/token", { name: b.dataset.tokenRemove, remove: true })).tokens; }
        catch (err) { AI.note.token = err.message; }
        renderAi();
        return;
      }
      if (!b.dataset.ai) return;
      const id = b.closest("[data-provider]").dataset.provider;
      const what = b.dataset.ai;
      b.disabled = true;
      try {
        if (what === "check") {
          AI.note[id] = { text: "Asking…" };
          renderAi();
          const r = await api("/api/ai/check", { provider: id });
          AI.data = r;
          AI.note[id] = { text: r.text, bad: !r.ok };
        } else if (what === "models") {
          const r = await api("/api/ai/models", { provider: id });
          AI.note[id + ":models"] = r.models;
          AI.note[id] = { text: `${r.models.length} models: pick one in the Model field.` };
        } else if (what === "forget") {
          if (!confirm("Remove this key from the server?")) { b.disabled = false; return; }
          AI.data = await api("/api/ai/account", { provider: id, api_key: "" });
          AI.note[id] = { text: "Key removed." };
        }
      } catch (err) { AI.note[id] = { text: err.message, bad: true }; }
      renderAi();
    });
  }

  wire();
  wireAi();
})();
