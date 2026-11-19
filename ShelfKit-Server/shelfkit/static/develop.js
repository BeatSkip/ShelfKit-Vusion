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
    vmode: "show",              // show (on its tab) | popout (its own window)
    vbox: null,                 // the virtual tag panel; it moves into its own window when popped out
    vwin: null,
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
  const dirtyNames = () => [...new Set([...D.files.filter((f) => f.isNew).map((f) => f.name),
    ...Object.keys(D.edits).filter((n) => D.edits[n] !== textOf(n, true))])];
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
    $("dev-app-error").innerHTML = a && a.error ? CodeEdit.linkRefs(`Didn't load: ${a.error}`, fileNames()) : "";
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
        ${s.detail ? `<span class="dev-step-detail">${CodeEdit.linkRefs(s.detail, fileNames())}</span>` : ""}</span></li>`;
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
    const sett = p.settings || { vars: [], secrets: [] };
    const settRows = [
      ...sett.vars.map((v) => `<li><span class="dev-sett-kind">variable</span><code>${esc(v.name)}</code>
        ${v.new === null ? '<span class="dev-del">remove</span>'
    : `${v.old != null ? `<s>${esc(v.old)}</s> → ` : '<span class="dev-add">new</span> '}<code class="dev-sett-val">${esc(v.new)}</code>`}</li>`),
      ...sett.secrets.map((x) => `<li><span class="dev-sett-kind">secret</span><code>${esc(x.name)}</code>
        ${x.action === "remove" ? '<span class="dev-del">remove</span>'
    : x.action === "set" ? `<span class="dev-add">${x.exists ? "new value" : "new"}</span> <span class="hint">(the value you gave in your request)</span>`
      : open ? `<input type="password" class="dev-sett-secret" data-secret-for="${esc(x.name)}" autocomplete="new-password" value="${esc((D.secretDraft || {})[x.name] || "")}"
          placeholder="${x.token ? "optional: the API token of this name is used" : "type its value"}" aria-label="Value for the secret ${esc(x.name)}">
          ${x.why ? `<span class="hint">${esc(x.why)}</span>` : ""}`
        : '<span class="hint">asked for</span>'}</li>`),
    ].join("");
    const settHtml = settRows ? `<div class="dev-sett"><span class="dev-sett-title">Settings</span><ul>${settRows}</ul></div>` : "";
    const diff = D.diff ? `<div class="dev-diff">${p.stats.map((s) =>
      `<div class="dev-diff-file"><div class="dev-diff-name">${esc(s.name)}</div>${diffHtml(p.before[s.name] || "", p.files[s.name], s.name)}</div>`).join("")}</div>` : "";
    return `<li class="dev-step dev-change ${p.broken ? "is-broken" : ""}">
      <div class="dev-change-head">
        <span class="dev-change-title">${p.broken ? "Proposed change, with problems" : "Proposed change"}</span>
        ${stats}
      </div>
      ${settHtml}
      ${open && j.preview ? `<button type="button" class="dev-change-shot" data-vtab title="Open it on the Virtual tag tab">
        <img src="data:image/png;base64,${j.preview}" alt="The proposed screen"></button>` : ""}
      <p class="dev-change-note">${open ? `Not saved. ${j.preview ? "The Virtual tag tab shows it. " : ""}Accept writes ${p.stats.length ? "the files (a checkpoint is saved first)" : ""}${p.stats.length && p.settings ? " and " : ""}${p.settings ? "the settings" : ""}.`
        : j.status === "accepted" ? "Accepted and saved." : "Rejected: the files did not change."}</p>
      <div class="dev-change-actions">
        ${p.stats.length ? `<button type="button" data-diff aria-pressed="${D.diff}">${D.diff ? "Hide diff" : "Show diff"}</button>` : ""}
        ${open ? `${p.stats.length ? `<button type="button" data-take title="Put the proposed files in the editor as unsaved edits${settRows ? " (the settings change waits for Accept)" : ""}">Edit first</button>` : ""}
        <span class="spacer"></span>
        <button type="button" data-reject>Reject</button>
        <button type="button" class="primary" data-accept>${p.broken ? "Accept anyway" : "Accept"}</button>` : ""}
      </div>
      ${diff}
    </li>`;
  }

  // a line diff (longest common subsequence), enough for app-sized files
  function diffHtml(a, b, name) {
    const x = a.split("\n"), y = b.split("\n");
    if (x.length * y.length > 4e6) return '<p class="hint">Too large to compare here.</p>';
    const n = x.length, m = y.length;
    const t = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
    for (let i = n - 1; i >= 0; i--) for (let k = m - 1; k >= 0; k--) {
      t[i][k] = x[i] === y[k] ? t[i + 1][k + 1] + 1 : Math.max(t[i + 1][k], t[i][k + 1]);
    }
    const out = [];
    let i = 0, k = 0;
    while (i < n || k < m) {          // [sign, text, old line, new line]
      if (i < n && k < m && x[i] === y[k]) { out.push([" ", x[i], i + 1, k + 1]); i++; k++; }
      else if (i < n && (k >= m || t[i + 1][k] >= t[i][k + 1])) { out.push(["-", x[i], i + 1, null]); i++; }
      else { out.push(["+", y[k], null, k + 1]); k++; }
    }
    const lang = CodeEdit.lang(name || "");
    // only changed lines with two lines of context
    const keep = out.map((_, idx) => out.slice(Math.max(0, idx - 2), idx + 3).some((l) => l[0] !== " "));
    let html = "", gap = false;
    out.forEach((l, idx) => {
      if (!keep[idx]) { if (!gap) html += '<div class="dev-dl dev-gap">⋯</div>'; gap = true; return; }
      gap = false;
      const cls = l[0] === "+" ? "dev-dl-add" : l[0] === "-" ? "dev-dl-del" : "";
      const code = CodeEdit.highlight(lang, l[1]).replace(/\n$/, "") || " ";
      html += `<div class="dev-dl ${cls}" ${l[3] ? `data-diff-goto="${esc(name)}:${l[3]}" title="Open ${esc(name)} at line ${l[3]}"` : ""}><span class="dev-dl-n">${l[2] ?? ""}</span><span class="dev-dl-n">${l[3] ?? ""}</span><span class="dev-dl-sign">${l[0]}</span><span class="dev-dl-code">${code}</span></div>`;
    });
    return `<pre class="dev-diff-body">${html}</pre>`;
  }

  async function accept() {
    if (!D.job) return;
    D.busy = true;
    try {
      const secrets = {};
      for (const i of document.querySelectorAll(".dev-sett-secret")) if (i.value) secrets[i.dataset.secretFor] = i.value;
      D.secretDraft = {};
      const r = await api("/api/dev/agent/apply", { job: D.job.id, secrets });
      D.job.status = "accepted";
      D.edits = {};
      D.msg = r.error ? { text: `Saved, but the app didn't load: ${r.error}`, bad: true }
        : { text: "Saved and reloaded. A checkpoint of the old files is under Versions." };
      if (r.error) D.job.suggestions = [`Fix this load error: ${r.error}`.slice(0, 300)];
      if ((r.missing_secrets || []).length && !r.error) {
        D.msg = { text: `Saved. Still to fill in on the Settings tab: the secret${r.missing_secrets.length > 1 ? "s" : ""} ${r.missing_secrets.join(", ")}.`, bad: true };
      }
      D.settings = null;           // the Settings tab reads them again
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
  const hasPhone = (a) => !!a && ((a.controls || []).length > 0 || !!a.has_on_open || !!a.has_page);
  const hasTap = (a) => !!a && (!!a.has_on_open || !!a.has_on_tap);

  function setTab(tab) {
    D.tab = tab;
    store("dev.tab", tab);
    renderTabs();
    renderPane();
    if (tab === "settings") loadSettings();
    else if (tab !== "code" && tab !== "virtual" && tab !== "phone") refreshSide();
  }

  function renderTabs() {
    const phoneTab = document.querySelector('#dev-tabs [data-tab="phone"]');
    phoneTab.hidden = !hasPhone(appOf(D.app));
    if (D.tab === "phone" && phoneTab.hidden) D.tab = "code";
    for (const b of document.querySelectorAll("#dev-tabs [data-tab]")) {
      b.setAttribute("aria-selected", String(b.dataset.tab === D.tab));
    }
  }

  function renderPane() {
    const pane = $("dev-pane");
    pane.style.minHeight = `${pane.offsetHeight}px`;
    requestAnimationFrame(() => { pane.style.minHeight = ""; });
    const msg = D.msg ? `<p class="dev-msg ${D.msg.bad ? "bad" : ""}" role="status">${CodeEdit.linkRefs(D.msg.text, fileNames())}</p>` : "";
    if (!D.app) {
      pane.innerHTML = '<p class="hint">No apps yet. Make one with New app on the Apps screen.</p>';
      return;
    }
    renderVmode();
    if (D.tab === "virtual") {
      pane.innerHTML = msg + (D.vmode === "popout" ? `<div class="dev-vt-away"><p>The virtual tag is in its own window.</p>
        <button type="button" data-vdock>Bring it back to this tab</button></div>` : "");
    }
    else if (D.tab === "phone") { pane.innerHTML = msg + phoneHtml(); wirePhone(); }
    else if (D.tab === "settings") pane.innerHTML = msg + settingsHtml();
    else if (D.tab === "versions") pane.innerHTML = msg + versionsHtml();
    else if (D.tab === "debug") pane.innerHTML = msg + debugHtml();
    else {
      pane.innerHTML = msg + codeHtml();
      const ed = $("dev-editor");
      if (ed) {
        ed.value = textOf(D.file);
        const v = (D.view || {})[D.file];
        if (v) {
          ed.setSelectionRange(Math.min(v.pos, ed.value.length), Math.min(v.end, ed.value.length));
          ed.scrollTop = v.top;
          ed.scrollLeft = v.left;
        }
        D.caretLine = ed.value.slice(0, ed.selectionStart).split("\n").length;
        paintEditor();
      }
    }
  }

  // ── the code editor: an explorer on the left, a highlighted editor on the right ──
  const LINE_H = 20;            // px; must match .ide-hl / .ide-input in style.css
  const PAD = 12;
  const FILE_ICON = {
    python: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M8 1.5c-3 0-3 1.3-3 2.3V5h3.2v.6H3.6C2.4 5.6 1.5 6.6 1.5 8.3s.9 2.9 2.1 2.9H5V9.6c0-1.2 1-2.1 2.2-2.1h3c1 0 1.8-.8 1.8-1.8V3.8c0-1-.9-2.3-4-2.3z" fill="#3b78b0"/><path d="M8 14.5c3 0 3-1.3 3-2.3V11H7.8v-.6h4.6c1.2 0 2.1-1 2.1-2.7s-.9-2.9-2.1-2.9H11v1.6c0 1.2-1 2.1-2.2 2.1h-3c-1 0-1.8.8-1.8 1.8v2.2c0 1 .9 2.3 4 2.3z" fill="#e0b532"/></svg>',
    xml: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M5.5 4 2 8l3.5 4M10.5 4 14 8l-3.5 4" fill="none" stroke="#d9534f" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></svg>',
    json: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M6 2.5c-1.5 0-2 .7-2 2v1.6c0 .8-.5 1.4-1.5 1.9 1 .5 1.5 1.1 1.5 1.9v1.6c0 1.3.5 2 2 2M10 2.5c1.5 0 2 .7 2 2v1.6c0 .8.5 1.4 1.5 1.9-1 .5-1.5 1.1-1.5 1.9v1.6c0 1.3-.5 2-2 2" fill="none" stroke="#c49a1a" stroke-width="1.5" stroke-linecap="round"/></svg>',
    text: '<svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M4 2.5h5.5L12.5 5.5V13a.5.5 0 0 1-.5.5H4a.5.5 0 0 1-.5-.5V3a.5.5 0 0 1 .5-.5z" fill="none" stroke="currentColor" stroke-width="1.2"/><path d="M5.5 8h5M5.5 10.5h4" stroke="currentColor" stroke-width="1.2"/></svg>',
  };
  const fileNames = () => D.files.map((f) => f.name);
  const allTexts = () => Object.fromEntries(D.files.map((f) => [f.name, textOf(f.name)]));

  function codeHtml() {
    const dirty = new Set(dirtyNames());
    const lang = CodeEdit.lang(D.file);
    const files = D.files.map((f) => {
      const l = CodeEdit.lang(f.name);
      return `<li><button type="button" class="ide-file" data-file="${esc(f.name)}"
        aria-current="${f.name === D.file ? "true" : "false"}" title="${esc(f.name)}">${FILE_ICON[l]}
        <span class="ide-file-name">${esc(f.name)}</span>${f.isNew ? '<span class="ide-new-tag">new</span>' : ""}${D.files.indexOf(f) < 9 ? `<kbd class="ide-key" title="Alt+${D.files.indexOf(f) + 1}">${D.files.indexOf(f) + 1}</kbd>` : ""}${dirty.has(f.name) ? '<span class="dev-dot" title="Unsaved"></span>' : ""}</button></li>`;
    }).join("");
    const note = fileNote(lang);
    return `
      <div class="ide">
        <nav class="ide-side" aria-label="Explorer">
          <div class="ide-side-title ide-side-head">Explorer
            <button type="button" class="ide-side-btn" data-file-menu title="New file… (or right-click the explorer)"
              aria-label="New file" aria-haspopup="menu"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M8 3v10M3 8h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></button></div>
          <div class="ide-folder" title="inkapps/${esc(D.app)}"><svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M1.5 4.5v8a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1V6a1 1 0 0 0-1-1H8L6.5 3.5h-4a1 1 0 0 0-1 1z" fill="none" stroke="currentColor" stroke-width="1.2"/></svg>
            ${esc(D.app)}</div>
          <ul class="ide-files" id="dev-files">${files}</ul>
          <div class="ide-side-title">Outline</div>
          <ul class="ide-outline" id="dev-outline"></ul>
        </nav>
        <div class="ide-main">
          <div class="ide-tabbar">
            <span class="ide-tab">${FILE_ICON[lang]}<span>${esc(D.file)}</span>${dirty.has(D.file) ? '<span class="dev-dot"></span>' : ""}</span>
            <span class="ide-crumb">inkapps / ${esc(D.app)} / ${esc(D.file)}</span>
          </div>
          <div class="ide-code" data-lang="${lang}">
            <pre class="ide-gutter" id="dev-gutter" aria-hidden="true"></pre>
            <div class="ide-area">
              <div class="ide-curline" id="dev-curline" aria-hidden="true"></div>
              <pre class="ide-hl" id="dev-hl" aria-hidden="true"></pre>
              <textarea id="dev-editor" class="ide-input" spellcheck="false" autocomplete="off" autocapitalize="off"
                wrap="off" aria-label="${esc(D.file)}"></textarea>
            </div>
          </div>
          <div class="ide-status">
            <span id="dev-pos">Ln 1, Col 1</span>
            <span id="dev-lang">${esc(CodeEdit.LANG_NAME[lang])}</span>
            <span class="ide-status-note" id="dev-note">${esc(note)}</span>
            <span class="ide-status-tip" id="dev-goto-note">Ctrl+click or F12: go to definition</span>
          </div>
          <div class="ide-problems" id="dev-problems">${problemsHtml()}</div>
        </div>
      </div>`;
  }

  const fileNote = (lang) => (lang === "xml" ? "Drawn on the virtual tag as you type, not saved"
    : lang === "python" ? "Runs in the server only after Save and reload" : "Saved with the app");
  const tabHtml = (name) => `${FILE_ICON[CodeEdit.lang(name)]}<span>${esc(name)}</span>${dirtyNames().includes(name) ? '<span class="dev-dot"></span>' : ""}`;

  // another file in the editor, without rebuilding the tab: nothing on the page moves
  function switchFile(name) {
    const ed = $("dev-editor");
    if (!ed || D.tab !== "code" || !D.files.some((f) => f.name === name)) {
      D.file = name;
      renderPane();
      return;
    }
    if (name === D.file) return;
    caretMoved();                       // remembers where the old file's caret and scroll were
    D.file = name;
    const lang = CodeEdit.lang(name);
    for (const b of document.querySelectorAll(".ide-file")) b.setAttribute("aria-current", String(b.dataset.file === name));
    document.querySelector(".ide-tab").innerHTML = tabHtml(name);
    document.querySelector(".ide-crumb").textContent = `inkapps / ${D.app} / ${name}`;
    document.querySelector(".ide-code").dataset.lang = lang;
    $("dev-lang").textContent = CodeEdit.LANG_NAME[lang];
    $("dev-note").textContent = fileNote(lang);
    $("dev-goto-note").textContent = "Ctrl+click or F12: go to definition";
    $("dev-goto-note").classList.remove("is-miss");
    ed.setAttribute("aria-label", name);
    ed.value = textOf(name);
    const v = (D.view || {})[name] || { pos: 0, end: 0, top: 0, left: 0 };
    ed.setSelectionRange(Math.min(v.pos, ed.value.length), Math.min(v.end, ed.value.length));
    ed.scrollTop = v.top;
    ed.scrollLeft = v.left;
    D.caretLine = ed.value.slice(0, ed.selectionStart).split("\n").length;
    $("dev-gutter").dataset.lines = "";
    paintEditor();
    $("dev-problems").innerHTML = problemsHtml();
    ed.focus({ preventScroll: true });
    layoutDraft();
  }

  // ── the explorer's context menu ──────────────────────────────────────────
  const FILE_NAME = /^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,60}\.(py|xml|md|json|txt|toml|sprite)$/;   // develop.EDITABLE
  const NEW_KINDS = {
    file: { label: "New file…", ext: "", text: () => "" },
    py: { label: "New Python module…", ext: ".py", text: (n) => `"""${n}: part of the ${D.app} app."""\n` },
    xml: { label: "New layout…", ext: ".xml",
      text: () => '<screen padding="4" gap="4">\n  <text size="20" bold="true">{{ data.title | default:"Hello" }}</text>\n</screen>\n' },
  };
  let menuEl = null;

  function closeFileMenu() {
    if (!menuEl) return;
    menuEl.remove();
    menuEl = null;
  }

  function openFileMenu(x, y, file) {
    closeFileMenu();
    const f = file && D.files.find((g) => g.name === file);
    const items = [
      ...Object.entries(NEW_KINDS).map(([k, v]) => ({ act: `new:${k}`, label: v.label })),
      ...(f ? [
        { sep: true },
        { act: "dup", label: "Duplicate…" },
        { act: "copy", label: "Copy name" },
        { act: "del", label: f.isNew ? "Remove (not saved yet)" : "Delete", danger: true, off: f.name === "app.py",
          hint: f.name === "app.py" ? "app.py is the app itself" : "" },
      ] : []),
    ];
    menuEl = document.createElement("div");
    menuEl.className = "ide-menu";
    menuEl.setAttribute("role", "menu");
    menuEl.setAttribute("aria-label", f ? f.name : "Explorer");
    menuEl.innerHTML = (f ? `<div class="ide-menu-title">${esc(f.name)}</div>` : "") + items.map((it) => it.sep
      ? '<div class="ide-menu-sep" role="separator"></div>'
      : `<button type="button" role="menuitem" data-act="${it.act}" ${it.off ? "disabled" : ""}
          class="${it.danger ? "is-danger" : ""}" title="${esc(it.hint || "")}">${esc(it.label)}</button>`).join("");
    document.body.appendChild(menuEl);
    const r = menuEl.getBoundingClientRect();
    menuEl.style.left = `${Math.max(4, Math.min(x, innerWidth - r.width - 4))}px`;
    menuEl.style.top = `${Math.max(4, Math.min(y, innerHeight - r.height - 4))}px`;
    menuEl.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (!b || b.disabled) return;
      closeFileMenu();
      fileAction(b.dataset.act, f ? f.name : null);
    });
    menuEl.addEventListener("keydown", (e) => {
      const list = [...menuEl.querySelectorAll("button:not([disabled])")];
      const i = list.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); list[(i + 1) % list.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); list[(i - 1 + list.length) % list.length].focus(); }
      else if (e.key === "Home") { e.preventDefault(); list[0].focus(); }
      else if (e.key === "End") { e.preventDefault(); list[list.length - 1].focus(); }
      else if (e.key === "Escape" || e.key === "Tab") {
        e.preventDefault();
        closeFileMenu();
        document.querySelector(`.ide-file[data-file="${CSS.escape(file || D.file)}"]`)?.focus();
      }
    });
    menuEl.querySelector("button:not([disabled])").focus();
  }

  function fileAction(act, file) {
    if (act.startsWith("new:")) return nameNewFile(act.slice(4), null, file);
    if (act === "dup") return nameNewFile("dup", file, file);
    if (act === "copy") { navigator.clipboard?.writeText(file).catch(() => {}); return; }
    if (act === "del") return deleteFile(file);
  }

  // an input in the file list, like an IDE: Enter makes the file, Escape gives up
  function nameNewFile(kind, source, after) {
    if (D.tab !== "code") { D.tab = "code"; store("dev.tab", "code"); renderTabs(); renderPane(); }
    const list = $("dev-files");
    if (!list) return;
    list.querySelector(".ide-naming")?.remove();
    const ext = source ? (source.match(/\.[a-z]+$/) || [""])[0] : NEW_KINDS[kind].ext;
    const li = document.createElement("li");
    li.className = "ide-naming";
    li.innerHTML = `<input type="text" spellcheck="false" autocomplete="off" aria-label="Name of the new file"
      placeholder="${source ? "copy name" : ext ? `name${ext}` : "name.py, .xml, .md, .json, .txt"}"><span class="ide-naming-err" role="alert"></span>`;
    const at = after && list.querySelector(`.ide-file[data-file="${CSS.escape(after)}"]`);
    if (at) at.closest("li").after(li); else list.appendChild(li);
    const input = li.querySelector("input");
    const err = li.querySelector(".ide-naming-err");
    if (source) {
      const base = source.replace(/\.[a-z]+$/, "");
      let n = 2;
      while (D.files.some((f) => f.name === `${base}_${n}${ext}`)) n += 1;
      input.value = `${base}_${n}${ext}`;
      input.setSelectionRange(0, input.value.length - ext.length);
    }
    input.focus();
    let done = false;
    const check = () => {
      let name = input.value.trim();
      if (name && ext && !/\.[A-Za-z0-9]+$/.test(name)) name += ext;
      if (!name) return { error: "" };
      if (!FILE_NAME.test(name)) {
        return { error: /\.[A-Za-z0-9]+$/.test(name) ? "Use .py, .xml, .md, .json, .txt, .toml or .sprite, and letters, digits, - _ ."
          : "Add an extension: .py, .xml, .md, .json, .txt, .toml or .sprite" };
      }
      if (D.files.some((f) => f.name.toLowerCase() === name.toLowerCase())) return { error: `There is already a ${name}` };
      return { name };
    };
    input.addEventListener("input", () => { err.textContent = check().error || ""; li.classList.toggle("is-bad", !!err.textContent); });
    input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); done = true; li.remove(); $("dev-editor")?.focus({ preventScroll: true }); }
      else if (e.key === "Enter") {
        e.preventDefault();
        const c = check();
        if (!c.name) { err.textContent = c.error || "Type a name"; li.classList.add("is-bad"); return; }
        done = true;
        createFile(c.name, source ? textOf(source) : NEW_KINDS[kind].text(c.name.replace(/\.[a-z]+$/, "")));
      }
    });
    input.addEventListener("blur", () => { setTimeout(() => { if (!done) li.remove(); }, 120); });
  }

  function createFile(name, text) {
    caretMoved();
    D.files.push({ name, text: "", isNew: true });
    D.edits[name] = text;
    D.file = name;
    D.msg = { text: `${name} is new and not saved yet: Save and reload writes it to the app's folder.` };
    renderHead();
    renderPane();
    layoutDraft();
    const ed = $("dev-editor");
    if (ed) { ed.focus({ preventScroll: true }); ed.setSelectionRange(ed.value.length, ed.value.length); caretMoved(); }
  }

  async function deleteFile(name) {
    const f = D.files.find((g) => g.name === name);
    if (!f || name === "app.py") return;
    if (f.isNew) {
      D.files = D.files.filter((g) => g !== f);
      delete D.edits[name];
    } else {
      const unsaved = dirtyNames().includes(name) ? " Its unsaved edits go too." : "";
      if (!confirm(`Delete ${name} from the app? A checkpoint of the files is saved first, so Versions can bring it back.${unsaved}`)) return;
      try {
        const r = await api("/api/dev/delete", { app: D.app, file: name });
        delete D.edits[name];
        const keep = { ...D.edits };
        await loadApps();
        await loadApp();
        D.edits = keep;            // edits to the other files stay
        D.msg = r.error ? { text: `Deleted ${name}, but the app didn't load: ${r.error}`, bad: true }
          : { text: `Deleted ${name} and reloaded the app. The checkpoint is under Versions.` };
      } catch (e) {
        D.msg = { text: e.message, bad: true };
      }
    }
    if (D.file === name || !D.files.some((g) => g.name === D.file)) D.file = "app.py";
    renderAll();
  }

  function problemsHtml() {
    if (!D.file.endsWith(".xml")) return "";
    const list = D.draft && D.draft.diagnostics ? D.draft.diagnostics
      : D.vt && D.vt.diagnostics && !(D.file in D.edits) ? D.vt.diagnostics : null;
    return list ? diagHtml(list) : "";
  }

  function diagHtml(list) {
    const shown = list.filter((d) => d.level !== "info");
    if (!shown.length) return '<p class="dev-diag-ok">No layout problems.</p>';
    const xml = D.files.find((f) => f.name.endsWith(".xml"));
    const names = fileNames();
    return `<ul class="dev-diags">${shown.map((d) => `<li class="is-${esc(d.level)}"><span>${esc(d.level)}</span>
      ${xml ? `<button type="button" class="code-ref" data-goto-at="${esc(d.at)}" title="Show it in ${esc(xml.name)}">${esc(d.at)}</button>`
    : `<code>${esc(d.at)}</code>`} ${CodeEdit.linkRefs(d.msg, names, xml && xml.name)}</li>`).join("")}</ul>`;
  }

  // the editor's layers: highlighted text, line numbers, the caret's line, the outline
  function paintEditor() {
    const ed = $("dev-editor");
    if (!ed) return;
    const text = ed.value;
    $("dev-hl").innerHTML = CodeEdit.highlight(CodeEdit.lang(D.file), text);
    const lines = text.split("\n").length;
    const g = $("dev-gutter");
    if (Number(g.dataset.lines) !== lines) {
      g.textContent = Array.from({ length: lines }, (_, k) => k + 1).join("\n") + "\n";
      g.dataset.lines = lines;
    }
    const out = CodeEdit.outline(CodeEdit.lang(D.file), text);
    $("dev-outline").innerHTML = out.length ? out.map((o) => `<li><button type="button" data-line="${o.line}"
      style="--depth: ${o.depth}" title="Line ${o.line}"><span class="ide-ol-label">${esc(o.label)}</span>
      ${o.kind ? `<span class="ide-ol-kind">${esc(o.kind)}</span>` : ""}</button></li>`).join("")
      : '<li class="ide-ol-none">Nothing to outline</li>';
    syncScroll();
    caretMoved();
  }

  function syncScroll() {
    const ed = $("dev-editor");
    if (!ed) return;
    $("dev-hl").style.transform = `translate(${-ed.scrollLeft}px, ${-ed.scrollTop}px)`;
    $("dev-gutter").style.transform = `translateY(${-ed.scrollTop}px)`;
    placeCurline();
  }

  function caretMoved() {
    const ed = $("dev-editor");
    if (!ed) return;
    const pos = ed.selectionStart;
    const before = ed.value.slice(0, pos);
    const ln = before.split("\n").length;
    const col = pos - before.lastIndexOf("\n");
    const sel = Math.abs(ed.selectionEnd - ed.selectionStart);
    $("dev-pos").textContent = `Ln ${ln}, Col ${col}${sel ? ` (${sel} selected)` : ""}`;
    D.caretLine = ln;
    (D.view || (D.view = {}))[D.file] = { pos, end: ed.selectionEnd, top: ed.scrollTop, left: ed.scrollLeft };
    placeCurline();
    for (const b of document.querySelectorAll("#dev-outline [data-line]")) b.removeAttribute("aria-current");
    const items = [...document.querySelectorAll("#dev-outline [data-line]")].filter((b) => Number(b.dataset.line) <= ln);
    if (items.length) items[items.length - 1].setAttribute("aria-current", "true");
  }

  function placeCurline() {
    const ed = $("dev-editor"), cur = $("dev-curline");
    if (!ed || !cur) return;
    cur.style.transform = `translateY(${PAD + ((D.caretLine || 1) - 1) * LINE_H - ed.scrollTop}px)`;
    const g = $("dev-gutter");
    g.style.setProperty("--cur", `${PAD + ((D.caretLine || 1) - 1) * LINE_H}px`);
  }

  // open a file at a line (and column), scrolled into the middle, the line flashed
  function goto(file, line, col) {
    if (!D.files.some((f) => f.name === file)) return;
    if (D.tab !== "code") { D.tab = "code"; store("dev.tab", "code"); renderTabs(); }
    if (!$("dev-editor")) { D.file = file; renderPane(); }
    else if (file !== D.file) switchFile(file);
    const ed = $("dev-editor");
    const lines = ed.value.split("\n");
    const ln = Math.max(1, Math.min(lines.length, Number(line) || 1));
    let pos = 0;
    for (let k = 0; k < ln - 1; k++) pos += lines[k].length + 1;
    pos += Math.max(0, Math.min(lines[ln - 1].length, (Number(col) || 1) - 1));
    ed.focus({ preventScroll: true });
    ed.setSelectionRange(pos, pos);
    ed.scrollTop = Math.max(0, (ln - 1) * LINE_H - ed.clientHeight / 3);
    D.caretLine = ln;
    syncScroll();
    caretMoved();
    const cur = $("dev-curline");
    cur.classList.remove("flash");
    void cur.offsetWidth;
    cur.classList.add("flash");
    $("dev-editor").closest(".ide").scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  function gotoDefinition() {
    const ed = $("dev-editor");
    if (!ed) return;
    const hit = CodeEdit.definition(allTexts(), D.file, ed.value, ed.selectionStart);
    if (hit.file) goto(hit.file, hit.line, hit.col);
    const note = $("dev-goto-note");      // after goto: another file is a new status bar
    if (note) { note.textContent = hit.note; note.classList.toggle("is-miss", !hit.file); }
  }

  function gotoAt(path) {
    const xml = D.files.find((f) => f.name.endsWith(".xml"));
    if (!xml) return;
    const line = CodeEdit.xmlLine(textOf(xml.name), path);
    goto(xml.name, line || 1);
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
            <dt>Result</dt><dd>${vt.error ? `<span class="dev-bad">${CodeEdit.linkRefs(vt.error, fileNames(), "layout.xml")}</span>` : vt.png ? "drawn" : "—"}</dd>
          </dl>
          ${vt.diagnostics ? diagHtml(vt.diagnostics) : ""}
          <h4>What the layout gets (@app.data)</h4>
          <pre class="json">${esc(JSON.stringify(vt.data ?? {}, null, 1))}</pre>
          <h4>tag.data</h4>
          <pre class="json">${esc(JSON.stringify(vt.state ?? {}, null, 1))}</pre>
        </section>
        <section>
          <div class="dev-log-head"><h3>The app's log</h3><button type="button" data-relog>Refresh</button></div>
          <pre class="json dev-log">${log ? CodeEdit.linkRefs(log, fileNames(), "layout.xml") : "Nothing logged yet."}</pre>
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
        const sprites = Object.fromEntries(Object.entries(D.edits).filter(([n]) => n.endsWith(".sprite")));
        const r = await api("/api/layout/render", { layout: D.edits[name], data: (D.vt && D.vt.data) || {},
          app: D.app, files: sprites });
        if (seq !== D.layoutSeq) return;
        D.draft = { png: r.png, diagnostics: r.diagnostics };
      } catch (e) {
        D.draft = { png: null, diagnostics: [{ level: "error", at: name, msg: e.message }] };
      }
      renderVirtual();
      const box = $("dev-problems");
      if (box) box.innerHTML = problemsHtml();
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
    if (D.tab === "debug" || D.tab === "phone") renderPane();
    if (what !== "draw") refreshSide();
  }

  function renderVirtual() {
    const box = D.vbox;
    const a = appOf(D.app);
    renderVmode();
    if (!a) { box.innerHTML = ""; return; }
    if (D.vwin && !D.vwin.closed) {
      D.vwin.document.title = `Virtual tag · ${a.title || a.id}`;
      D.vwin.document.documentElement.dataset.theme = document.documentElement.dataset.theme || "light";
    }
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
        ${D.vmode === "popout"
    ? `<button type="button" class="dev-vt-icon" data-vdock title="Put the virtual tag back in the page" aria-label="Put the virtual tag back in the page"><svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M2.5 3.5h11v9h-11zM9.5 3.5v9" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/></svg></button>`
    : `<button type="button" class="dev-vt-icon" data-vpop title="Open the virtual tag in its own window" aria-label="Open the virtual tag in its own window"><svg viewBox="0 0 16 16" width="15" height="15" aria-hidden="true"><path d="M9.5 2.5h4v4M13.5 2.5 8 8M12 9.5V13a.5.5 0 0 1-.5.5h-8A.5.5 0 0 1 3 13V5a.5.5 0 0 1 .5-.5H7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/></svg></button>`}
      </div>
      <p class="dev-vt-app">${esc(a.title || a.id)}</p>
      <div class="dev-vt-screen">
      ${prop ? `<span class="apps-seg dev-which" role="group" aria-label="Show">
        <button type="button" data-which="now" aria-pressed="${!D.showProposal}">Now</button>
        <button type="button" data-which="prop" aria-pressed="${D.showProposal}">Proposal</button></span>` : ""}
      <span class="tag-case" style="--glass-w: ${(/^landscape/.test(a.screen_orientation || "") ? 296 : 152) * k}px; --glass-h: ${(/^landscape/.test(a.screen_orientation || "") ? 152 : 296) * k}px"><span class="glass">${src
    ? `<img src="data:image/png;base64,${src}" alt="The virtual tag's screen">`
    : `<span class="dev-glass-err">${esc(vt.error || "Drawing…")}</span>`}</span></span>
      <span class="app-glass-cap">${esc(cap)}${vt.ms != null && src === vt.png ? ` · ${vt.ms} ms` : ""}</span>
      ${vt.error && src ? `<p class="dev-bad dev-vt-err">${CodeEdit.linkRefs(vt.error, fileNames(), "layout.xml")}</p>` : ""}
      </div>
      <div class="dev-vt-side">
      <div class="dev-vt-group">
        <label class="dev-pretend">Pretend it is
          <input type="datetime-local" id="dev-pretend" value="${esc(D.pretend)}"></label>
        ${D.pretend ? '<button type="button" data-now>Now</button>' : ""}
      </div>
      <div class="app-glass-actions">
        <button type="button" data-vt="draw">Draw again</button>
        ${(a.timers || []).length ? `<button type="button" data-vt="timers" title="Runs every @app.every timer once">Run timers</button>` : ""}
        ${hasTap(a) ? '<button type="button" data-vt="open" title="Runs what an NFC tap runs">Simulate NFC tap</button>' : ""}
      </div>
      ${controls ? `<div class="dev-vt-group dev-vt-col"><span class="dev-vt-label">Phone page</span>${controls}</div>` : ""}
      ${fields ? `<form class="dev-vt-group dev-vt-col dev-vt-config" id="dev-config"><span class="dev-vt-label">Settings for this tag</span>
        ${fields}<button type="submit">Use these settings</button></form>` : ""}
      <button type="button" class="dev-vt-reset" data-vt="reset" title="Forget the virtual tag's data and settings">Reset the virtual tag</button>
      </div>`;
  }

  // where the panel is: on its tab, or in its own window
  function renderVmode() {
    if (!D.vbox) return;
    const inTab = D.tab === "virtual";
    D.vbox.hidden = D.vmode !== "popout" && !inTab;
    $("dev-pane").hidden = inTab && D.vmode !== "popout" && !D.msg;
    const t = document.querySelector('#dev-tabs [data-tab="virtual"]');
    t.textContent = D.vmode === "popout" ? "Virtual tag ↗" : "Virtual tag";
    t.title = D.vmode === "popout" ? "The virtual tag is in its own window" : "";
  }

  // ── Settings: the app's variables and secrets (the same for every tag) ──
  async function loadSettings() {
    const app = D.app;
    if (!app) return;
    try {
      const r = await fetch(`/api/dev/settings?app=${encodeURIComponent(app)}`);
      const j = await r.json();
      if (!r.ok) throw new Error(j.error || r.statusText);
      if (app !== D.app) return;
      D.settings = { app, ...j };
    } catch (e) {
      D.settings = { app, error: e.message };
    }
    if (D.tab === "settings") renderPane();
  }

  async function saveSetting(kind, name, value, remove = false) {
    try {
      const r = await api("/api/dev/settings", { app: D.app, kind, name, value, remove });
      D.settings = { ...D.settings, ...r };
      D.setMsg = { text: remove ? `Removed ${name}.` : `Saved ${name}. The virtual tag was drawn again with it.` };
      renderPane();
      virtual("draw");
      return true;
    } catch (e) {
      D.setMsg = { text: e.message, bad: true };
      renderPane();
      return false;
    }
  }

  function settingsHtml() {
    const st = D.settings;
    if (!st || st.app !== D.app) { loadSettings(); return '<p class="hint">Loading…</p>'; }
    if (st.error) return `<p class="dev-bad">${esc(st.error)}</p>`;
    const note = D.setMsg ? `<p class="dev-msg ${D.setMsg.bad ? "bad" : ""}" role="status">${esc(D.setMsg.text)}</p>` : "";
    D.setMsg = null;
    const vars = st.vars.map((v) => `<form class="dev-set-row" data-kind="var" data-name="${esc(v.name)}">
        <code class="dev-set-name">${esc(v.name)}</code>
        <input name="value" value="${esc(v.value)}" aria-label="Value of ${esc(v.name)}" spellcheck="false">
        <button type="submit">Save</button>
        <button type="button" class="dev-set-del" data-set-del="var" data-name="${esc(v.name)}" aria-label="Remove ${esc(v.name)}">Remove</button>
      </form>`).join("");
    const secrets = st.secrets.map((x) => `<form class="dev-set-row" data-kind="secret" data-name="${esc(x.name)}">
        <code class="dev-set-name">${esc(x.name)}</code>
        <input name="value" type="password" autocomplete="new-password" placeholder="${esc(x.hint)} · type to replace"
          aria-label="New value for ${esc(x.name)}">
        <button type="submit">Replace</button>
        <button type="button" class="dev-set-del" data-set-del="secret" data-name="${esc(x.name)}" aria-label="Remove ${esc(x.name)}">Remove</button>
      </form>`).join("");
    const fields = (st.fields || []).map((f) => `<tr><td><code>${esc(f.key)}</code></td><td>${esc(f.label)}</td>
      <td>${f.default ? `<code>${esc(f.default)}</code>` : '<span class="hint">empty</span>'}</td></tr>`).join("");
    return `${note}<div class="dev-settings">
      <section class="dev-set-card">
        <h3>Variables</h3>
        <p class="hint">Plain values the app uses on every tag: a city, a URL, a threshold. Read them with
          <code>tag.var("name", "default")</code>; they are always text. The AI sees them.</p>
        <div class="dev-set-list">${vars || '<p class="hint dev-set-none">No variables yet.</p>'}</div>
        <form class="dev-set-row dev-set-add" data-kind="var" data-add>
          <input name="name" placeholder="name" aria-label="New variable's name" spellcheck="false" autocomplete="off">
          <input name="value" placeholder="value" aria-label="New variable's value" spellcheck="false" autocomplete="off">
          <button type="submit" class="primary">Add</button>
        </form>
      </section>
      <section class="dev-set-card">
        <h3>Secrets</h3>
        <p class="hint">Keys and passwords for this app. Read them with <code>tag.secret("name")</code>. They are kept in the
          server's database, not in the app's files, so they stay out of git and checkpoints, and the AI only sees their names.</p>
        <div class="dev-set-list">${secrets || '<p class="hint dev-set-none">No secrets yet.</p>'}</div>
        <form class="dev-set-row dev-set-add" data-kind="secret" data-add>
          <input name="name" placeholder="name" aria-label="New secret's name" spellcheck="false" autocomplete="off">
          <input name="value" type="password" placeholder="value" aria-label="New secret's value" autocomplete="new-password">
          <button type="submit" class="primary">Add</button>
        </form>
        <p class="hint">Shared API tokens: <code>tag.secret</code> falls back to these when the app has no secret of that name.
          ${st.tokens.length ? st.tokens.map((t) => `<code>${esc(t)}</code>`).join(" ") : "none yet."}
          <a href="#settings" data-ai-settings>Manage them in Settings › AI services</a></p>
      </section>
      <section class="dev-set-card">
        <h3>Per-tag settings</h3>
        <p class="hint">Declared in app.py with <code>app.config_field(key, label=, default=)</code> and read with
          <code>tag.config["key"]</code>. Each tag has its own values, set on the Apps screen; the virtual tag's are on the Virtual tag tab.</p>
        ${fields ? `<table class="dev-set-fields"><thead><tr><th>Key</th><th>Label</th><th>Default</th></tr></thead><tbody>${fields}</tbody></table>`
    : '<p class="hint dev-set-none">This app declares none.</p>'}
      </section>
    </div>`;
  }

  // the phone page as the app's phone would show it (the server builds it; no scripts run in it)
  function phoneHtml() {
    const a = appOf(D.app);
    const vt = D.vt || {};
    return `<div class="dev-phone-wrap">
      <div class="dev-phone">
        <div class="dev-phone-bar"><span>tag/FFF0</span></div>
        ${vt.phone ? `<iframe id="dev-phone-frame" title="The app's phone page" sandbox="allow-same-origin allow-forms"></iframe>`
    : `<p class="dev-phone-none">${esc(vt.error || "Drawing…")}</p>`}
      </div>
      <div class="dev-phone-side">
        <p class="hint">This is the page a phone opens when it taps a tag running <strong>${esc(a ? a.title || a.id : "")}</strong>,
          here for the virtual tag. Its buttons run the app's code for the virtual tag; nothing is sent to a real tag.</p>
        ${hasTap(a) ? `<button type="button" data-vt-open title="Runs @app.on_tap and @app.on_open, as a tap on the tag does">Simulate NFC tap</button>` : ""}
        <p class="hint">A real phone reaches it at <code>/tag/&lt;ID&gt;</code> on this server, through your reverse proxy.</p>
      </div>
    </div>`;
  }

  function wirePhone() {
    const f = $("dev-phone-frame");
    if (!f) return;
    f.srcdoc = (D.vt || {}).phone || "";
    f.addEventListener("load", () => {
      const doc = f.contentDocument;
      if (!doc) return;
      doc.addEventListener("submit", (e) => {
        e.preventDefault();
        const form = e.target;
        const action = form.elements.action && form.elements.action.value;
        const value = form.elements.value ? form.elements.value.value : null;
        if (action) virtual("action", { action, value });
      });
    });
  }

  function popOut() {
    if (D.vwin && !D.vwin.closed) { D.vwin.focus(); return; }
    const w = window.open("", "shelfkit-virtual-tag", "popup,width=460,height=900");
    if (!w) { D.msg = { text: "The browser blocked the new window: allow pop-ups for this page.", bad: true }; renderPane(); return; }
    const sheets = [...document.querySelectorAll('link[rel="stylesheet"]')]
      .map((l) => `<link rel="stylesheet" href="${esc(new URL(l.getAttribute("href"), location.href).href)}">`).join("");
    w.document.open();
    w.document.write(`<!doctype html><html lang="en" data-theme="${esc(document.documentElement.dataset.theme || "light")}">
      <head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
      <title>Virtual tag</title>${sheets}</head><body class="vtag-window"></body></html>`);
    w.document.close();
    w.document.body.appendChild(w.document.adoptNode(D.vbox));
    D.vwin = w;
    D.vmode = "popout";
    if (D.tab === "virtual") renderPane();
    w.addEventListener("pagehide", () => { if (D.vmode === "popout") dock(true); });
    renderVirtual();
  }

  // back into the page; closed = the window is going away by itself
  function dock(closed) {
    const w = D.vwin;
    D.vwin = null;
    if (D.vbox.ownerDocument !== document) $("dev-pane").after(document.adoptNode(D.vbox));
    D.vmode = "show";
    if (!closed && w && !w.closed) w.close();
    renderVirtual();
    if (D.tab === "virtual") renderPane();
  }

  // the panel handles its own events, so they work in the page and in its own window
  function wireVirtual(box) {
    const ask = (q) => (box.ownerDocument.defaultView || window).confirm(q);
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button, a");
      if (!b) return;
      if (b.dataset.goto) {
        const [file, line, col] = b.dataset.goto.split(":");
        window.focus();
        goto(file, Number(line), Number(col) || 1);
      }
      else if (b.matches("[data-vpop]")) popOut();
      else if (b.matches("[data-vdock]")) dock(false);
      else if (b.dataset.vt) {
        if (b.dataset.vt === "reset" && !ask("Forget the virtual tag's data and settings?")) return;
        virtual(b.dataset.vt);
      }
      else if (b.dataset.which) { D.showProposal = b.dataset.which === "prop"; renderVirtual(); }
      else if (b.dataset.vscale) { store("dev.scale", b.dataset.vscale); renderVirtual(); }
      else if (b.matches("[data-now]")) { D.pretend = ""; virtual("draw"); }
      else if (b.dataset.ctl && b.tagName === "BUTTON" && !b.closest("form")) virtual("action", { action: b.dataset.ctl });
    });
    box.addEventListener("submit", (e) => {
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
    box.addEventListener("change", (e) => {
      if (e.target.id === "dev-pretend") { D.pretend = e.target.value; virtual("draw"); }
    });
  }

  // ── events ───────────────────────────────────────────────────────────────
  // Side by side: the agent is a column right of the code and the page itself never scrolls
  const CHAT_W = { min: 300, max: 760 };
  function applyLayout() {
    const split = stored("dev.layout", "split") === "split";
    document.querySelector('.screen[data-screen="develop"]').classList.toggle("dev-split", split);
    $("dev-layout").setAttribute("aria-pressed", String(split));
    const w = Number(stored("dev.chatw", "420")) || 420;
    document.querySelector(".dev-body").style.setProperty("--dev-chat-w", `${w}px`);
    $("dev-grip").setAttribute("aria-valuenow", String(w));
    if (split) window.scrollTo(0, 0);
  }

  function setChatWidth(w) {
    const body = document.querySelector(".dev-body");
    const room = body.getBoundingClientRect().width - 420;        // leave the code at least this much
    w = Math.round(Math.max(CHAT_W.min, Math.min(CHAT_W.max, room, w)));
    body.style.setProperty("--dev-chat-w", `${w}px`);
    $("dev-grip").setAttribute("aria-valuenow", String(w));
    store("dev.chatw", String(w));
  }

  function wireLayout() {
    $("dev-layout").addEventListener("click", () => {
      store("dev.layout", stored("dev.layout", "split") === "split" ? "stacked" : "split");
      applyLayout();
    });
    const grip = $("dev-grip");
    grip.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      grip.setPointerCapture(e.pointerId);
      const right = $("dev-chat").getBoundingClientRect().right;
      const move = (ev) => setChatWidth(right - ev.clientX);
      const up = () => {
        grip.removeEventListener("pointermove", move);
        grip.removeEventListener("pointerup", up);
        grip.removeEventListener("pointercancel", up);
        document.body.classList.remove("dev-resizing");
      };
      document.body.classList.add("dev-resizing");
      grip.addEventListener("pointermove", move);
      grip.addEventListener("pointerup", up);
      grip.addEventListener("pointercancel", up);
    });
    grip.addEventListener("keydown", (e) => {
      const step = e.shiftKey ? 80 : 20;
      const w = $("dev-chat").getBoundingClientRect().width;
      if (e.key === "ArrowLeft") { e.preventDefault(); setChatWidth(w + step); }
      else if (e.key === "ArrowRight") { e.preventDefault(); setChatWidth(w - step); }
    });
    grip.addEventListener("dblclick", () => setChatWidth(420));
    // the agent's feed follows new steps while you are at its bottom, like a chat
    const feed = $("dev-agent");
    feed.addEventListener("input", (e) => {
      if (e.target.matches(".dev-sett-secret")) (D.secretDraft ||= {})[e.target.dataset.secretFor] = e.target.value;
    });
    let stick = true;
    feed.addEventListener("scroll", () => { stick = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 60; });
    new MutationObserver(() => { if (stick) feed.scrollTop = feed.scrollHeight; })
      .observe(feed, { childList: true, subtree: true, characterData: true });
    applyLayout();
  }

  function wireFileMenu(screenEl) {
    screenEl.addEventListener("contextmenu", (e) => {
      const side = e.target.closest(".ide-side");
      if (!side || e.target.closest("#dev-outline, .ide-naming")) return;
      e.preventDefault();
      openFileMenu(e.clientX, e.clientY, e.target.closest(".ide-file")?.dataset.file || null);
    });
    screenEl.addEventListener("keydown", (e) => {
      const b = e.target.closest && e.target.closest(".ide-file");
      if (b && (e.key === "ContextMenu" || (e.key === "F10" && e.shiftKey))) {
        e.preventDefault();
        const r = b.getBoundingClientRect();
        openFileMenu(r.left + 24, r.bottom, b.dataset.file);
      } else if (b && e.key === "Delete" && b.dataset.file !== "app.py") {
        e.preventDefault();
        deleteFile(b.dataset.file);
      }
    });
    document.addEventListener("pointerdown", (e) => { if (menuEl && !menuEl.contains(e.target)) closeFileMenu(); }, true);
    window.addEventListener("resize", closeFileMenu);
    window.addEventListener("blur", closeFileMenu);
    document.addEventListener("scroll", closeFileMenu, true);
  }

  function wireSettings() {
    const pane = $("dev-pane");
    pane.addEventListener("submit", async (e) => {
      const f = e.target.closest(".dev-set-row");
      if (!f) return;
      e.preventDefault();
      const name = f.dataset.add !== undefined ? f.elements.name.value.trim() : f.dataset.name;
      const value = f.elements.value.value;
      if (f.dataset.kind === "secret" && !value) { f.elements.value.focus(); return; }
      if (f.dataset.add !== undefined && st0(name)) return;
      await saveSetting(f.dataset.kind, name, value);
    });
    const st0 = (name) => {
      const s = D.settings || {};
      if ([...(s.vars || []), ...(s.secrets || [])].some((x) => x.name === name)) {
        D.setMsg = { text: `There is already a setting called ${name}; change it in its row.`, bad: true };
        renderPane();
        return true;
      }
      return false;
    };
    pane.addEventListener("click", (e) => {
      const b = e.target.closest("[data-set-del]");
      if (!b) return;
      if (!confirm(`Remove ${b.dataset.setDel === "secret" ? "the secret" : "the variable"} ${b.dataset.name}?`)) return;
      saveSetting(b.dataset.setDel, b.dataset.name, null, true);
    });
  }

  function wire() {
    wireLayout();
    wireSettings();
    D.vbox = $("dev-virtual");
    wireVirtual(D.vbox);
    window.addEventListener("pagehide", () => { if (D.vwin && !D.vwin.closed) D.vwin.close(); });
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
      if (screenIs("develop") && e.altKey && !e.ctrlKey && !e.metaKey && /^Digit[1-9]$/.test(e.code)) {
        const f = D.files[Number(e.code.slice(5)) - 1];
        if (f) {
          e.preventDefault();
          if (D.tab !== "code") { D.tab = "code"; store("dev.tab", "code"); renderTabs(); D.file = f.name; renderPane(); }
          else switchFile(f.name);
        }
        return;
      }
      if (screenIs("develop") && e.key.toLowerCase() === "k" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        $("dev-ask").focus();
      }
    });
    $("dev-tabs").addEventListener("click", (e) => {
      const b = e.target.closest("[data-tab]");
      if (!b) return;
      setTab(b.dataset.tab);
    });

    const screenEl = document.querySelector('.screen[data-screen="develop"]');
    wireFileMenu(screenEl);
    screenEl.addEventListener("click", (e) => {
      if (e.target.closest("#dev-virtual")) return;     // the panel handles its own (wireVirtual)
      const dl = e.target.closest("[data-diff-goto]");
      if (dl && !e.target.closest("button")) {
        const [file, line] = dl.dataset.diffGoto.split(":");
        if (D.job && D.job.status === "proposed" && D.job.proposal.files[file] !== undefined) takeProposal();
        goto(file, Number(line));
        return;
      }
      const b = e.target.closest("button, a");
      if (!b) return;
      if (b.dataset.goto) {
        const [file, line, col] = b.dataset.goto.split(":");
        goto(file, Number(line), Number(col) || 1);
        return;
      }
      if (b.dataset.gotoAt) { gotoAt(b.dataset.gotoAt); return; }
      if (b.matches("[data-vdock]")) { dock(false); return; }
      if (b.matches("[data-file-menu]")) { const r = b.getBoundingClientRect(); openFileMenu(r.left, r.bottom + 4, null); return; }
      if (b.matches("[data-vt-open]")) { virtual("open"); return; }
      if (b.matches("[data-vtab]")) { D.showProposal = true; setTab("virtual"); renderVirtual(); return; }
      if (b.dataset.line && b.closest("#dev-outline")) { goto(D.file, Number(b.dataset.line)); return; }
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
      else if (b.dataset.file) switchFile(b.dataset.file);
      else if (b.dataset.revert) revert(b.dataset.revert);
      else if (b.matches("[data-relog]")) refreshSide();
    });
    screenEl.addEventListener("input", (e) => {
      if (e.target.id !== "dev-editor") return;
      D.edits[D.file] = e.target.value;
      renderHead();
      paintEditor();
      const dirty = D.edits[D.file] !== textOf(D.file, true);
      for (const el of [document.querySelector(`.ide-file[data-file="${CSS.escape(D.file)}"]`), document.querySelector(".ide-tab")]) {
        if (!el) continue;
        if (dirty && !el.querySelector(".dev-dot")) el.insertAdjacentHTML("beforeend", '<span class="dev-dot" title="Unsaved"></span>');
        if (!dirty) el.querySelector(".dev-dot")?.remove();
      }
      if (D.file.endsWith(".xml")) layoutDraft();
    });
    screenEl.addEventListener("keydown", (e) => {
      if (e.target.id !== "dev-editor") return;
      const ed = e.target;
      const indent = CodeEdit.lang(D.file) === "python" ? "    " : "  ";
      if (e.key === "Tab" && !e.ctrlKey && !e.altKey) {
        e.preventDefault();
        const { selectionStart: s, selectionEnd: t, value: v } = ed;
        const multi = v.slice(s, t).includes("\n");
        if (!multi && !e.shiftKey) { document.execCommand("insertText", false, indent); return; }
        // indent or outdent every selected line
        const a = v.lastIndexOf("\n", s - 1) + 1;
        const block = v.slice(a, t);
        const lines = block.split("\n");
        const changed = lines.map((l) => e.shiftKey ? l.replace(new RegExp(`^ {1,${indent.length}}`), "") : indent + l).join("\n");
        ed.setSelectionRange(a, t);
        document.execCommand("insertText", false, changed);
        ed.setSelectionRange(a, a + changed.length);
      } else if (e.key === "Enter" && !e.ctrlKey && !e.metaKey) {
        e.preventDefault();
        const v = ed.value, s = ed.selectionStart;
        const line = v.slice(v.lastIndexOf("\n", s - 1) + 1, s);
        let pad = /^\s*/.exec(line)[0];
        if (CodeEdit.lang(D.file) === "python" && /:\s*(#.*)?$/.test(line)) pad += indent;
        if (CodeEdit.lang(D.file) === "xml" && /<[A-Za-z][^<>]*[^/]>\s*$/.test(line) && !/<\//.test(line)) pad += indent;
        document.execCommand("insertText", false, "\n" + pad);
      } else if (e.key === "F12") {
        e.preventDefault();
        gotoDefinition();
      } else if (e.key === "s" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        saveFiles();
      }
    });
    screenEl.addEventListener("scroll", (e) => { if (e.target.id === "dev-editor") syncScroll(); }, true);
    screenEl.addEventListener("keyup", (e) => { if (e.target.id === "dev-editor") caretMoved(); });
    screenEl.addEventListener("mouseup", (e) => {
      if (e.target.id !== "dev-editor") return;
      caretMoved();
      if (e.ctrlKey || e.metaKey) setTimeout(gotoDefinition, 0);
    });
    document.addEventListener("selectionchange", () => {
      if (document.activeElement && document.activeElement.id === "dev-editor") caretMoved();
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
  // app.js picks the remembered Settings tab before this file loads: fill AI services now if it is the one shown
  if (!document.querySelector('section[data-tab="ai"]').hidden) window.aiSettingsShown();
})();
