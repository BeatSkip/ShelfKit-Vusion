"use strict";

/* The Apps screen (InkServices). Loaded after app.js and uses its globals: $, screen,
 * stored, store, ageText.
 *
 * Left: the installed apps. Right: the picked app - the tags it runs on, the picked
 * tag's current screen with its settings and the app's phone controls, what the app
 * has stored, and its log.
 *
 * Unlike the rest of the page this is not drawn from /api/poll: it fetches
 * /api/inkapps while the screen is open (every APPS_POLL_MS and after each action).
 * The detail is rebuilt only when its shape changes (other app, other tag, a tag
 * bound or unbound), so a refresh never wipes a settings field being typed in. The
 * preview is fetched again only when something could have changed it.
 */
(function () {
  const APPS_POLL_MS = 5000;
  const A = {
    list: null,             // /api/inkapps
    data: null,             // /api/inkapps/data for the picked app
    log: [],
    app: stored("apps.app", ""),
    tag: {},                // app id -> picked tag (one it runs on)
    cand: {},               // app id -> tag picked in "Run on"
    bump: 0,                // bumped after every action: the preview may have changed
    msg: null,              // {text, bad} under the picked tag
    shape: "",
    listShape: "",
    previewKey: "",
    seq: 0,
    error: "",
  };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  async function api(path, body) {
    const opts = body === undefined ? {} :
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  const current = () => (A.list ? A.list.apps.find((a) => a.id === A.app) : null);
  const tagInfo = (hex) => (A.list ? A.list.tags.find((t) => t.id === hex) : null) || { id: hex };
  const ranBy = (hex) => {
    const b = A.list ? A.list.bindings.find((x) => x.hex_id === hex) : null;
    return b ? b.app_id : null;
  };
  const binding = (hex) => (A.list ? A.list.bindings.find((x) => x.hex_id === hex) : null);
  const tagLabel = (hex) => {
    const t = tagInfo(hex);
    return t.alias ? `${hex} · ${t.alias}` : hex;
  };

  // ── fetching ─────────────────────────────────────────────────────────────
  async function load() {
    const mine = ++A.seq;
    try {
      const list = await api("/api/inkapps");
      if (mine !== A.seq) return;
      A.list = list;
      if (!list.apps.some((a) => a.id === A.app)) A.app = list.apps.length ? list.apps[0].id : "";
      A.error = "";
      if (A.app) {
        const app = encodeURIComponent(A.app);
        const [data, log] = await Promise.all([
          api(`/api/inkapps/data?app=${app}`).catch(() => null),
          api(`/api/inkapps/log?app=${app}`).catch(() => ({ log: [] })),
        ]);
        if (mine !== A.seq) return;
        A.data = data;
        A.log = log.log || [];
      }
    } catch (err) {
      if (mine !== A.seq) return;
      A.error = err.message;
    }
    renderApps();
  }

  // ── drawing ──────────────────────────────────────────────────────────────
  function renderApps() {
    const listBox = $("apps-list");
    const detail = $("apps-detail");
    $("apps-problem").hidden = !A.error;
    $("apps-problem").textContent = A.error;
    if (!A.list) return;
    const apps = A.list.apps;
    $("apps-empty").hidden = apps.length > 0;
    $("apps-body").hidden = apps.length === 0;

    const listShape = JSON.stringify([A.app, apps.map((a) => [a.id, a.title, a.error, a.tags])]);
    if (listShape !== A.listShape) {
      A.listShape = listShape;
      listBox.innerHTML = apps.map((a) => {
        const sub = a.error ? '<span class="bad">Did not load</span>'
          : a.tags.length ? `On ${a.tags.length === 1 ? "tag " + a.tags[0] : a.tags.length + " tags"}`
            : "Not running";
        return `<button type="button" class="app-item" data-app="${esc(a.id)}"
          ${a.id === A.app ? 'aria-current="true"' : ""}>
          <span class="app-item-title">${esc(a.title)}</span>
          <span class="app-item-sub">${sub}</span></button>`;
      }).join("");
    }

    const a = current();
    if (!a) { detail.innerHTML = ""; A.shape = ""; return; }
    if (!a.tags.includes(A.tag[a.id])) A.tag[a.id] = a.tags[0] || null;
    const cands = candidates(a);
    if (!cands.some((t) => t.id === A.cand[a.id])) A.cand[a.id] = cands.length ? cands[0].id : null;

    const shape = JSON.stringify([a, A.tag[a.id], A.cand[a.id], A.list.tags,
      cands.map((t) => [t.id, ranBy(t.id)]), A.list.phone_base]);
    if (shape !== A.shape) {
      A.shape = shape;
      A.previewKey = "";
      detail.innerHTML = detailHtml(a, cands);
      const box = $("app-data-box");
      box.open = stored("apps.data.open", "0") === "1";
      box.addEventListener("toggle", () => store("apps.data.open", box.open ? "1" : "0"));
    }
    renderLive(a);
  }

  function candidates(a) {
    return A.list.tags.filter((t) => !a.tags.includes(t.id));
  }

  function detailHtml(a, cands) {
    const tag = A.tag[a.id];
    const kind = a.error ? "did not load" : a.layout ? `drawn from ${esc(a.layout)}` : "draws in Python";
    const parts = [`
      <div class="app-head">
        <h2>${esc(a.title)}</h2>
        <p class="hint"><code>${esc(a.id)}</code> · ${kind}${(a.timers || []).length
          ? ` · updates itself every ${Math.min(...a.timers.map((t) => t.minutes))} min` : ""}</p>
        ${a.description ? `<p class="app-desc">${esc(a.description)}</p>` : ""}
        ${a.error ? `<pre class="app-error">${esc(a.error)}</pre>
          <p class="hint">Fix the app in <code>inkapps/${esc(a.id)}/</code>, then press Reload apps.
          Its tags keep their last picture until then.</p>` : ""}
      </div>`];

    // the tags it runs on, and running it on another
    const rows = a.tags.map((hex) => `
      <tr data-tag="${hex}" class="${hex === tag ? "open" : ""}">
        <td><button type="button" class="id-link" data-pick="${hex}"
             aria-pressed="${hex === tag}">${hex}</button></td>
        <td>${esc(tagInfo(hex).alias || "")}</td>
        <td data-sent="${hex}"></td>
        <td class="app-row-act">
          ${a.error ? "" : `<button type="button" data-refresh="${hex}"
             title="Fetch fresh data, draw the screen again, and send it if it changed">Refresh now</button>`}
          <button type="button" class="quiet" data-stop="${hex}"
             title="The tag keeps its last picture until something else is sent">Stop</button>
        </td>
      </tr>`).join("");
    const opts = cands.map((t) => {
      const other = ranBy(t.id);
      return `<option value="${t.id}" ${t.id === A.cand[a.id] ? "selected" : ""}>${esc(tagLabel(t.id))}` +
        `${other ? ` (replaces ${esc(other)})` : ""}</option>`;
    }).join("");
    parts.push(`
      <section class="app-section" aria-labelledby="app-tags-title">
        <h3 id="app-tags-title">Tags</h3>
        ${rows ? `<div class="table-wrap"><table class="grid app-tags">
          <thead><tr><th>Tag</th><th>Alias</th><th>Last sent</th><th><span class="sr">Actions</span></th></tr></thead>
          <tbody>${rows}</tbody></table></div>`
          : '<p class="hint">Not running on any tag yet.</p>'}
        ${a.error ? "" : cands.length ? `
        <div class="row app-run">
          <select id="app-cand" aria-label="Tag to run the app on">${opts}</select>
          <button type="button" id="app-bind" class="${a.tags.length ? "" : "primary"}">Run on this tag</button>
        </div>` : A.list.tags.length
          ? '<p class="hint">Every tag the server knows already runs this app.</p>'
          : `<p class="hint">${a.tags.length ? "No other tags yet" : "No tags yet"}. A tag can be
             picked here once the hub has heard it.</p>`}
      </section>`);

    // the picked tag: its screen, settings and controls - or a preview before binding
    if (!a.error) {
      const shown = tag || A.cand[a.id] || "0000";
      const live = Boolean(tag);
      const fields = a.config_fields.map((f) => `
        <label>${esc(f.label)}
          <input name="${esc(f.key)}" type="text" spellcheck="false" placeholder="${esc(f.default)}">
        </label>`).join("");
      const controls = a.controls.map((c) => c.kind === "button"
        ? `<button type="button" data-act="${esc(c.id)}">${esc(c.label)}</button>`
        : `<span class="app-text"><input type="text" data-text="${esc(c.id)}" maxlength="500"
             placeholder="${esc(c.placeholder || c.label)}" aria-label="${esc(c.label)}">
           <button type="button" data-send="${esc(c.id)}">${esc(c.label)}</button></span>`).join("");
      const base = A.list.phone_base || "";
      const phone = `NFC link: <a href="${esc(base)}/tag/${shown}/view" target="_blank" rel="noopener"><code>${esc(base)}/tag/${shown}</code></a>` +
        (A.list.phone_base_local ? `<br>Only this computer can open it. Forward <code>/tag/</code> from a
          reverse proxy and enter its address under <a href="#settings">Settings</a>.` : "");
      parts.push(`
      <section class="app-section app-tag" aria-labelledby="app-tag-title">
        <div class="tag-case small-case"><div class="glass">
          <img id="app-preview" alt="What ${esc(a.title)} draws for ${shown}">
        </div></div>
        <div class="app-tag-side">
          <div>
            <h3 id="app-tag-title">${live ? esc(tagLabel(shown)) : `Preview on ${esc(tagLabel(shown))}`}</h3>
            <p class="hint">${live ? "What the app draws for this tag now."
              : "Nothing is sent until you press Run on this tag."}</p>
          </div>
          ${live && fields ? `<form id="app-config" class="app-fields" novalidate>
            <h4>Settings for this tag</h4>${fields}
            <button type="submit">Save settings</button></form>` : ""}
          ${live && (controls || a.has_on_open) ? `<div class="app-controls">
            <h4>What the phone page offers</h4>
            <div class="row">${controls}
              ${a.has_on_open ? '<button type="button" data-open title="Runs what an NFC tap runs">Simulate NFC tap</button>' : ""}
            </div></div>` : ""}
          ${live ? `<p class="hint">${phone}</p>` : ""}
          <p id="app-msg" class="app-msg" role="status"></p>
        </div>
      </section>`);
    }

    parts.push(`
      <details class="tool" id="app-data-box">
        <summary>Stored data</summary>
        <dl class="facts" id="app-data-facts"></dl>
        <h4>Shared by every tag</h4>
        <pre class="json" id="app-shared"></pre>
        <h4 id="app-tagdata-title" hidden></h4>
        <pre class="json" id="app-tagdata" hidden></pre>
      </details>
      <details class="tool" open>
        <summary>Log</summary>
        <div class="log app-log" id="app-log" tabindex="0" role="log" aria-label="App log"></div>
      </details>`);
    return parts.join("");
  }

  const json = (value) => JSON.stringify(value, null, 2);

  function renderLive(a) {
    const tag = A.tag[a.id];
    // when each tag last got a picture
    for (const cell of document.querySelectorAll("#apps-detail [data-sent]")) {
      const b = binding(cell.dataset.sent);
      cell.textContent = b && b.last_push_at ? `${ageText(Date.now() / 1000 - b.last_push_at)} ago` : "not yet";
    }

    // the preview, fetched again only when it could differ
    const img = $("app-preview");
    if (img) {
      const shown = tag || A.cand[a.id] || "0000";
      const b = binding(shown);
      const key = [a.id, shown, b && b.last_push_at, A.bump].join("|");
      if (key !== A.previewKey) {
        A.previewKey = key;
        img.src = `/api/inkapps/preview.png?app=${encodeURIComponent(a.id)}&tag=${shown}&v=${A.bump}-${Date.now()}`;
      }
    }

    const form = $("app-config");
    if (form && !form.dataset.filled && A.data) {
      const mine = A.data.tags.find((t) => t.hex_id === tag);
      for (const input of form.querySelectorAll("input[name]")) {
        const field = a.config_fields.find((f) => f.key === input.name);
        const value = mine ? mine.config[input.name] : "";
        input.value = value === undefined || (field && value === field.default) ? "" : value;
      }
      form.dataset.filled = "1";
    }

    const msg = $("app-msg");
    if (msg) {
      msg.textContent = A.msg ? A.msg.text : "";
      msg.classList.toggle("bad", Boolean(A.msg && A.msg.bad));
    }

    const d = A.data;
    const facts = $("app-data-facts");
    if (d && facts) {
      const others = d.tags.filter((t) => !t.bound).map((t) => t.hex_id);
      const rows = d.size === 0 ? [["File", `${d.path} (not created yet: the app has stored nothing)`]] : [
        ["File", d.path],
        ["Size", d.size >= 1024 ? `${(d.size / 1024).toFixed(1)} KB` : `${d.size} B`],
        ["Its own tables", d.tables.length ? d.tables.map((t) => `${t.name} (${t.rows} rows)`).join(", ") : "none"],
      ];
      if (others.length) rows.push(["Kept for", `${others.join(", ")} (no longer running the app)`]);
      facts.innerHTML = rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
      $("app-shared").textContent = json(d.shared);
      const mine = d.tags.find((t) => t.hex_id === tag);
      $("app-tagdata-title").hidden = $("app-tagdata").hidden = !mine;
      if (mine) {
        $("app-tagdata-title").textContent = `Tag ${tag}`;
        $("app-tagdata").textContent = json({ settings: mine.config, data: mine.state });
      }
    }

    const log = $("app-log");
    if (log) {
      const atEnd = log.scrollTop + log.clientHeight >= log.scrollHeight - 4;
      const text = A.log.map(([t, line]) => `${new Date(t * 1000).toLocaleTimeString()}  ${line}`).join("\n")
        || "Nothing logged since the server started.";
      if (log.textContent !== text) {
        log.textContent = text;
        if (atEnd) log.scrollTop = log.scrollHeight;
      }
    }
  }

  // ── acting ───────────────────────────────────────────────────────────────
  function outcome(r) {
    if (!r.ok) return { text: r.error || "That did not work.", bad: true };
    if (r.skipped === "identical") return { text: "The screen is unchanged, so nothing was sent (saves the tag's battery).", bad: false };
    if (r.skipped === "no on_open") return { text: "This app does nothing on a tap.", bad: false };
    if (r.pushed) return { text: "Queued. The tag shows it after its next check-in.", bad: false };
    return { text: "Done.", bad: false };
  }

  async function act(button, path, body, after) {
    if (button) button.disabled = true;
    try {
      A.msg = outcome(await api(path, body));
    } catch (err) {
      A.msg = { text: err.message, bad: true };
    }
    if (after) after();
    A.bump += 1;
    A.shape = "";             // rebuild: tags, settings and buttons may all have changed
    await load();
  }

  $("apps-list").addEventListener("click", (event) => {
    const item = event.target.closest("[data-app]");
    if (!item || item.dataset.app === A.app) return;
    A.app = item.dataset.app;
    store("apps.app", A.app);
    A.msg = null;
    A.data = null;
    A.log = [];
    load();
  });

  $("apps-detail").addEventListener("change", (event) => {
    if (event.target.id === "app-cand") {
      A.cand[A.app] = event.target.value;
      renderApps();
    }
  });

  $("apps-detail").addEventListener("submit", (event) => {
    if (event.target.id !== "app-config") return;
    event.preventDefault();
    const config = {};
    for (const input of event.target.querySelectorAll("input[name]")) {
      if (input.value !== "") config[input.name] = input.value;   // empty: the app's default
    }
    act(event.target.querySelector("button"), "/api/inkapps/config", { tag: A.tag[A.app], config });
  });

  $("apps-detail").addEventListener("click", (event) => {
    const b = event.target.closest("button");
    if (!b) return;
    const app = A.app;
    const tag = A.tag[app];
    if (b.dataset.pick) {
      A.tag[app] = b.dataset.pick;
      A.msg = null;
      renderApps();
    } else if (b.dataset.refresh) {
      A.tag[app] = b.dataset.refresh;
      act(b, "/api/inkapps/refresh", { tag: b.dataset.refresh });
    } else if (b.dataset.stop) {
      act(b, "/api/inkapps/unbind", { tag: b.dataset.stop });
    } else if (b.id === "app-bind") {
      const cand = A.cand[app];
      act(b, "/api/inkapps/bind", { tag: cand, app }, () => { A.tag[app] = cand; });
    } else if (b.dataset.act) {
      act(b, "/api/inkapps/action", { tag, action: b.dataset.act });
    } else if (b.dataset.send) {
      const input = b.parentElement.querySelector("[data-text]");
      act(b, "/api/inkapps/action", { tag, action: b.dataset.send, value: input.value });
    } else if (b.matches("[data-open]")) {
      act(b, "/api/inkapps/open", { tag });
    }
  });

  $("apps-reload").addEventListener("click", async () => {
    const b = $("apps-reload");
    b.disabled = true;
    try {
      await api("/api/inkapps/reload", {});
      A.shape = "";
      A.bump += 1;
      await load();
    } finally {
      b.disabled = false;
    }
  });

  window.renderApps = renderApps;
  window.appsShown = load;           // app.js calls this when the screen opens
  if (screen === "apps") load();     // the page was opened at #apps, before this file loaded
  setInterval(() => {
    if (screen === "apps" && !document.hidden) load();
  }, APPS_POLL_MS);
})();
