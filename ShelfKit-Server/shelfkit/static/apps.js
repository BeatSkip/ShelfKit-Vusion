"use strict";

/* The Apps screen (InkServices). Loaded after app.js and uses its globals: $, screen,
 * stored, store, ageText.
 *
 * Home: every enabled app as an icon in one grid, in the order the user dragged them
 * into, with groups (drop an app on another). Running apps (on at least one tag) are
 * filled, idle ones dashed, ones that failed to import red. Disabled apps sit in their
 * own section at the bottom, sorted by name or install date. Right-click (or hold) an
 * app or group for its menu. "New app" opens a wizard that writes inkapps/<id>/.
 *
 * App page: the app's tags as small tag cases, the picked tag's true-size screen with
 * its settings and phone controls, what the app stored, and its log.
 *
 * Not drawn from /api/poll: it fetches /api/inkapps while the screen is open (every
 * APPS_POLL_MS and after each action). Each part is rebuilt only when its shape
 * changes, never while a drag is under way, so a refresh never wipes a field being
 * typed in. The grid's order and groups are saved on the server (/api/inkapps/grid).
 */
(function () {
  const APPS_POLL_MS = 5000;
  const HOLD_MS = 550;          // press and hold: the context menu (touch screens)
  const A = {
    list: null,                 // /api/inkapps
    data: null,                 // /api/inkapps/data for the open app
    log: [],
    view: "",                   // "" the grid, else the open app's id
    items: [],                  // the grid: "app_id" or {id, name, apps: [...]}
    tag: {},                    // app id -> picked tag on its page
    msg: null,                  // {text, bad} on the app page
    icons: null,                // InkLayout pixel icons: name -> 12 rows of '#'/'.'
    openGroup: null,            // the group shown in the overlay
    drag: null,
    press: null,
    fresh: null,                // an app to make pulse once (just created or enabled)
    sortBy: stored("apps.dis.sort", "name"),
    sortAsc: stored("apps.dis.asc", "1") === "1",
    homeShape: "",
    railShape: "",
    scale: stored("apps.glass.scale", "2") === "1" ? 1 : 2,   // the preview on the right: 1x or 2x
    shape: "",
    previewKeys: {},
    bump: 0,
    seq: 0,
    error: "",
  };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const isGroup = (x) => typeof x !== "string";
  const keyOf = (x) => (isGroup(x) ? x.id : x);

  async function api(path, body) {
    const opts = body === undefined ? {} :
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
    const res = await fetch(path, opts);
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || res.statusText);
    return data;
  }

  const appOf = (id) => (A.list ? A.list.apps.find((a) => a.id === id) : null);
  const tagInfo = (hex) => (A.list ? A.list.tags.find((t) => t.id === hex) : null) || { id: hex };
  const binding = (hex) => (A.list ? A.list.bindings.find((x) => x.hex_id === hex) : null);
  const ranBy = (hex) => { const b = binding(hex); return b ? b.app_id : null; };
  const tagLabel = (hex) => { const t = tagInfo(hex); return t.alias ? `${hex} · ${t.alias}` : hex; };
  const tagName = (hex) => tagInfo(hex).alias || hex;
  const state = (a) => (a.disabled ? "off" : a.error ? "bad" : a.tags.length ? "run" : "idle");
  const plural = (n, one, many) => `${n} ${n === 1 ? one : many}`;
  const dateText = (t) => (t ? new Date(t * 1000).toLocaleDateString(undefined,
    { day: "numeric", month: "short", year: "numeric" }) : "unknown");

  // ── icons: InkLayout's own pixel icons, drawn as crisp SVG ───────────────────
  function iconSvg(a) {
    const rows = A.icons && a.icon ? A.icons[a.icon] : null;
    if (!rows) return `<span class="app-initial" aria-hidden="true">${esc((a.title || a.id || "?").trim()[0] || "?")}</span>`;
    let d = "";
    rows.forEach((row, y) => {
      for (let x = 0; x < row.length; x++) {
        if (row[x] !== "#") continue;
        let w = 1;
        while (row[x + w] === "#") w++;
        d += `M${x} ${y}h${w}v1h-${w}z`;
        x += w - 1;
      }
    });
    return `<svg viewBox="0 0 12 12" shape-rendering="crispEdges" aria-hidden="true"><path d="${d}" fill="currentColor"/></svg>`;
  }

  // ── fetching ─────────────────────────────────────────────────────────────
  async function load() {
    const mine = ++A.seq;
    try {
      const [list] = await Promise.all([
        api("/api/inkapps"),
        A.icons ? null : api("/api/layout/icons").then((r) => { A.icons = r.icons; }).catch(() => { A.icons = {}; }),
      ]);
      if (mine !== A.seq) return;
      A.list = list;
      A.error = "";
      if (A.view && !appOf(A.view)) A.view = "";
      if (A.view) {
        const app = encodeURIComponent(A.view);
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

  // The grid as saved, cleaned against what the server has now: apps that are gone or
  // disabled drop out, a group of one becomes the app, and apps the grid has never
  // seen (new folders) go at the end, oldest first.
  function buildItems() {
    const live = new Map(A.list.apps.filter((a) => !a.disabled).map((a) => [a.id, a]));
    const used = new Set();
    const out = [];
    for (const e of A.list.grid || []) {
      if (!isGroup(e)) {
        if (live.has(e) && !used.has(e)) { used.add(e); out.push(e); }
        continue;
      }
      const apps = (e.apps || []).filter((x) => live.has(x) && !used.has(x));
      apps.forEach((x) => used.add(x));
      if (apps.length > 1) out.push({ id: e.id, name: e.name, apps });
      else if (apps.length === 1) out.push(apps[0]);
    }
    const rest = [...live.keys()].filter((x) => !used.has(x))
      .sort((x, y) => (live.get(x).installed_at || 0) - (live.get(y).installed_at || 0));
    return out.concat(rest);
  }

  let saveTimer = 0;
  function saveGrid() {
    tidy();
    const grid = A.items.map((x) => (isGroup(x) ? { id: x.id, name: x.name, apps: [...x.apps] } : x));
    if (A.list) A.list.grid = grid;
    clearTimeout(saveTimer);
    saveTimer = setTimeout(() => {
      api("/api/inkapps/grid", { grid }).catch((err) => toast(`The layout was not saved: ${err.message}`, true));
    }, 300);
  }

  function tidy() {
    A.items = A.items.flatMap((x) => (!isGroup(x) ? [x] : x.apps.length === 0 ? []
      : x.apps.length === 1 ? [x.apps[0]] : [x]));
    if (A.openGroup && !A.items.includes(A.openGroup)) closeGroup();
  }

  // ── drawing: the grid ──────────────────────────────────────────────────────
  function appTile(id, ctx) {
    const a = appOf(id);
    if (!a) return "";
    const s = state(a);
    const n = a.tags.length;
    const badge = s === "run" ? `<span class="app-badge">${n}</span>`
      : s === "bad" ? '<span class="app-badge">!</span>' : "";
    const sub = s === "run" ? `<span class="app-dot"></span>${plural(n, "tag", "tags")}`
      : s === "bad" ? "Didn't load"
        : s === "off" ? (A.sortBy === "date" ? `Installed ${dateText(a.installed_at)}` : "Disabled")
          : "Idle";
    const what = s === "run" ? `running on ${plural(n, "tag", "tags")}` : s === "bad" ? "failed to load"
      : s === "off" ? "disabled" : "not running";
    return `<div class="app-tile is-${s}${id === A.fresh ? " fresh" : ""}" tabindex="0" role="button"
      data-key="${esc(id)}" data-ctx="${ctx}" aria-label="${esc(a.title)}, ${what}"
      title="${esc(a.description || a.title)}">
      <span class="app-ico">${iconSvg(a)}${badge}</span>
      <span class="app-name">${esc(a.title)}</span><span class="app-sub">${sub}</span></div>`;
  }

  function groupTile(g) {
    const apps = g.apps.map(appOf).filter(Boolean);
    const n = apps.filter((a) => state(a) === "run").length;
    const minis = apps.slice(0, 4).map((a) => `<span class="app-mini is-${state(a)}">${iconSvg(a)}</span>`).join("");
    return `<div class="app-tile is-group" tabindex="0" role="button" data-key="${esc(g.id)}" data-ctx="main"
      aria-label="Group ${esc(g.name)}, ${plural(apps.length, "app", "apps")}, ${n} running">
      <span class="app-ico">${minis}${n ? `<span class="app-badge">${n}</span>` : ""}</span>
      <span class="app-name">${esc(g.name)}</span>
      <span class="app-sub">${n ? `<span class="app-dot"></span>${n} of ${apps.length} running` : plural(apps.length, "app", "apps")}</span></div>`;
  }

  const NEW_TILE = `<div class="app-tile is-new" id="apps-new-tile" tabindex="0" role="button" aria-label="New app">
    <span class="app-ico"><svg viewBox="0 0 12 12" aria-hidden="true"><path d="M5.5 2h1v3.5H10v1H6.5V10h-1V6.5H2v-1h3.5z" fill="currentColor"/></svg></span>
    <span class="app-name">New app</span><span class="app-sub">&nbsp;</span></div>`;

  function disabledApps() {
    const off = A.list.apps.filter((a) => a.disabled);
    off.sort((x, y) => (A.sortBy === "date" ? (x.installed_at || 0) - (y.installed_at || 0)
      : x.title.localeCompare(y.title)));
    return A.sortAsc ? off : off.reverse();
  }

  function renderHome(anim) {
    const prev = {};
    if (anim) {
      for (const t of document.querySelectorAll("#apps .app-tile[data-key]")) {
        prev[t.dataset.key] = t.getBoundingClientRect();
      }
    }
    $("apps-grid").innerHTML = A.items.map((x) => (isGroup(x) ? groupTile(x) : appTile(x, "main"))).join("") + NEW_TILE;
    const off = disabledApps();
    $("apps-dis-grid").innerHTML = off.map((a) => appTile(a.id, "off")).join("")
      || '<p class="hint apps-dis-empty">Drag an app here to disable it. A disabled app keeps its files, settings and data.</p>';
    $("apps-dis-count").textContent = plural(off.length, "app", "apps");
    $("apps-sort-name").setAttribute("aria-pressed", A.sortBy === "name");
    $("apps-sort-date").setAttribute("aria-pressed", A.sortBy === "date");
    $("apps-sort-dir").textContent = A.sortBy === "name" ? (A.sortAsc ? "A to Z" : "Z to A")
      : (A.sortAsc ? "Oldest first" : "Newest first");
    if (A.openGroup) {
      $("apps-group-grid").innerHTML = A.openGroup.apps.map((id) => appTile(id, "group")).join("");
      if (document.activeElement !== $("apps-group-name")) $("apps-group-name").value = A.openGroup.name;
    }
    if (A.drag) {
      document.querySelector(`#apps .app-tile[data-key="${CSS.escape(A.drag.key)}"]`)?.classList.add("lifting");
      if (A.drag.merge) document.querySelector(`#apps-grid .app-tile[data-key="${CSS.escape(A.drag.merge)}"]`)?.classList.add("merge");
    }
    if (!anim || matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    for (const t of document.querySelectorAll("#apps .app-tile[data-key]")) {
      const p = prev[t.dataset.key];
      if (!p) continue;
      const r = t.getBoundingClientRect();
      const dx = p.left - r.left;
      const dy = p.top - r.top;
      if (dx || dy) {
        t.animate([{ transform: `translate(${dx}px, ${dy}px)` }, { transform: "none" }],
          { duration: 220, easing: "cubic-bezier(.2,.8,.2,1)" });
      }
    }
  }

  function renderApps() {
    $("apps-problem").hidden = !A.error;
    $("apps-problem").textContent = A.error;
    if (!A.list) return;
    if (!A.drag) {
      A.items = buildItems();
      if (A.openGroup) A.openGroup = A.items.find((x) => isGroup(x) && x.id === A.openGroup.id) || null;
      if (!A.openGroup) $("apps-group").hidden = true;
      const homeShape = JSON.stringify([A.items, A.list.apps.map((a) =>
        [a.id, a.title, a.icon, a.tags.length, Boolean(a.error), a.disabled, a.installed_at]),
      A.sortBy, A.sortAsc, Boolean(A.icons), A.fresh, Boolean(A.openGroup)]);
      if (homeShape !== A.homeShape) {
        A.homeShape = homeShape;
        renderHome(false);
      }
    }
    $("apps-home").hidden = Boolean(A.view);
    $("apps-detail").hidden = !A.view;
    $("apps").classList.toggle("is-detail", Boolean(A.view));
    if (A.view) { renderRail(); renderPage(); }
  }

  // ── drawing: the rail of apps beside an open app ───────────────────────────
  function railItem(id) {
    const a = appOf(id);
    if (!a) return "";
    const s = state(a);
    const n = a.tags.length;
    const sub = s === "run" ? `<span class="app-dot"></span>On ${plural(n, "tag", "tags")}`
      : s === "bad" ? "Didn't load" : s === "off" ? "Disabled" : "Not on a tag yet";
    const here = id === A.view;
    return `<button type="button" class="rail-app is-${s}" data-rail="${esc(id)}"
      ${here ? 'aria-current="page"' : ""} title="${esc(a.description || a.title)}">
      <span class="rail-ico">${iconSvg(a)}</span>
      <span class="rail-text"><span class="rail-name">${esc(a.title)}</span><span class="rail-sub">${sub}</span></span></button>`;
  }

  function renderRail() {
    const off = disabledApps();
    const shape = JSON.stringify([A.view, A.items, A.list.apps.map((a) =>
      [a.id, a.title, a.icon, a.tags.length, Boolean(a.error), a.disabled]), Boolean(A.icons),
    A.sortBy, A.sortAsc]);
    if (shape === A.railShape) return;
    A.railShape = shape;
    const rail = $("apps-rail");
    const top = rail.scrollTop;
    const left = rail.scrollLeft;
    const loose = A.items.filter((x) => !isGroup(x));
    const groups = A.items.filter(isGroup);
    const live = A.list.apps.length - off.length;
    rail.innerHTML = `<div class="rail-title">Installed · ${live}</div>
      <div class="rail-list">${loose.map(railItem).join("")}</div>
      ${groups.map((g) => `<div class="rail-title">${esc(g.name)}</div>
        <div class="rail-list">${g.apps.map(railItem).join("")}</div>`).join("")}
      ${off.length ? `<div class="rail-title">Disabled · ${off.length}</div>
        <div class="rail-list">${off.map((a) => railItem(a.id)).join("")}</div>` : ""}`;
    rail.scrollTop = top;
    rail.scrollLeft = left;
    const cur = rail.querySelector('[aria-current="page"]');
    if (cur) {
      const r = cur.getBoundingClientRect();
      const box = rail.getBoundingClientRect();
      if (r.top < box.top || r.bottom > box.bottom || r.left < box.left || r.right > box.right) {
        cur.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    }
  }

  // ── drawing: an app's page ─────────────────────────────────────────────────
  function renderPage() {
    const a = appOf(A.view);
    const page = $("apps-page");
    if (!a) { page.innerHTML = ""; A.shape = ""; return; }
    if (!a.tags.includes(A.tag[a.id])) A.tag[a.id] = a.tags[0] || null;
    const shape = JSON.stringify([a, A.tag[a.id], A.list.tags, A.list.tags.map((t) => ranBy(t.id)),
      A.list.phone_base, Boolean(A.icons)]);
    if (shape !== A.shape) {
      A.shape = shape;
      A.previewKeys = {};
      page.innerHTML = pageHtml(a);
      const box = $("app-data-box");
      if (box) {
        box.open = stored("apps.data.open", "0") === "1";
        box.addEventListener("toggle", () => store("apps.data.open", box.open ? "1" : "0"));
      }
    }
    renderLive(a);
  }

  const CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M20 6 9 17l-5-5"/></svg>';
  const DOTS = '<svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.7"/><circle cx="12" cy="12" r="1.7"/><circle cx="19" cy="12" r="1.7"/></svg>';

  function statusPill(a) {
    const s = state(a);
    if (s === "run") return `<span class="pill ok"><span class="app-dot"></span>Running on ${plural(a.tags.length, "tag", "tags")}</span>`;
    if (s === "bad") return '<span class="pill bad">Didn\'t load</span>';
    if (s === "off") return '<span class="pill">Disabled</span>';
    return `<span class="pill ok">${CHECK}Loaded</span>`;
  }

  // One card on the app's page: a label, maybe a button, and what it is.
  const appCard = (label, value, button, wide) => `
    <div class="app-card${wide ? " wide" : ""}">
      <div class="app-card-head"><span class="app-card-label">${label}</span>${button || ""}</div>
      <div class="app-card-value">${value}</div>
    </div>`;

  const quoted = (list) => list.length === 1 ? `“${list[0]}”`
    : `${list.slice(0, -1).map((x) => `“${x}”`).join(", ")} and “${list[list.length - 1]}”`;

  function cardsHtml(a, tag) {
    const out = [];
    const chips = a.tags.map((hex) => `<button type="button" class="app-chip" data-pick="${hex}"
        aria-pressed="${hex === tag}"><code>${hex}</code>${tagInfo(hex).alias ? ` ${esc(tagInfo(hex).alias)}` : ""}</button>`).join("");
    out.push(appCard("Runs on", a.tags.length ? `<span class="app-chips">${chips}</span>`
      : "Not on a tag yet. Pick one or more tags; each keeps its own settings and data.",
    '<button type="button" data-run>Choose tags</button>', true));
    if (a.config_fields.length) {
      out.push(appCard("Settings for each tag",
        a.config_fields.map((f) => esc(f.label) + (f.default !== "" && f.default != null ? ` (default ${esc(f.default)})` : "")).join("<br>"),
        tag ? '<button type="button" data-edit>Edit</button>' : ""));
    }
    const buttons = a.controls.filter((x) => x.kind === "button").map((x) => esc(x.label));
    const texts = a.controls.filter((x) => x.kind !== "button").map((x) => `A text box: ${esc(x.label)}`);
    const phone = [buttons.length ? `${quoted(buttons)} button${buttons.length > 1 ? "s" : ""}` : "", ...texts].filter(Boolean);
    if (phone.length) out.push(appCard("On the phone page", phone.join("<br>")));
    if (a.has_on_open) out.push(appCard("When a phone taps the tag", "Opens the phone page and runs the app"));
    const timers = [...new Set((a.timers || []).map((x) => `Every ${plural(x.minutes, "minute", "minutes")}`))];
    out.push(appCard("Timers", timers.length ? timers.join("<br>") : "None: redraws when someone uses the phone page"));
    return out;
  }

  function pageHtml(a) {
    const s = state(a);
    const tag = A.tag[a.id];
    const shown = tag || (A.list.tags[0] ? A.list.tags[0].id : "0000");
    const live = !a.disabled && !a.error;
    const actions = [];
    actions.push('<button type="button" data-code>Open the code</button>');
    if (a.disabled) actions.push('<button type="button" class="primary" id="app-enable">Enable app</button>');
    else if (live) {
      if (s === "run") actions.push('<button type="button" id="app-stop-all">Stop everywhere</button>');
      actions.push(`<button type="button" class="primary" data-run>${s === "run" ? "Run on another tag" : "Start on a tag"}</button>`);
    }
    actions.push(`<button type="button" id="app-more" class="icon-button" aria-haspopup="menu" aria-label="More for this app">${DOTS}</button>`);

    const main = [];
    if (a.disabled) {
      main.push(`<p class="app-note">A disabled app runs on no tag and its code is not loaded. Its files, settings and
        stored data stay in <code>inkapps/${esc(a.id)}/</code>.</p>`);
    } else if (a.error) {
      main.push(`<pre class="app-error">${esc(a.error)}</pre>
        <p class="hint">Fix the app in <code>inkapps/${esc(a.id)}/</code>, then press Reload apps.
        Its tags keep their last picture until then.</p>`);
    }
    const cards = live ? cardsHtml(a, tag) : [];
    cards.push(appCard("Files", `<code>inkapps/${esc(a.id)}/</code><br>${a.disabled ? "Not loaded"
      : a.error ? "Did not load" : a.layout ? `Drawn from ${esc(a.layout)}` : "Draws in Python"}<br>Installed ${dateText(a.installed_at)}`));
    main.push(`<div class="app-cards">${cards.join("")}</div>`);
    if (live) main.push(tag ? tagPanel(a, tag) : '<p id="app-msg" class="app-msg" role="status"></p>');
    main.push(`
      <section class="app-activity" aria-labelledby="app-log-title">
        <div class="app-activity-head"><h3 id="app-log-title">Activity</h3><span class="hint">Since the server started</span></div>
        <div class="log app-log" id="app-log" tabindex="0" role="log" aria-labelledby="app-log-title"></div>
      </section>
      <details class="tool" id="app-data-box">
        <summary>Stored data</summary>
        <dl class="facts" id="app-data-facts"></dl>
        <h4>Shared by every tag</h4>
        <pre class="json" id="app-shared"></pre>
        <h4 id="app-tagdata-title" hidden></h4>
        <pre class="json" id="app-tagdata" hidden></pre>
      </details>`);

    const k = A.scale;
    const glass = `
      <aside class="app-glass" aria-label="Screen preview">
        <div class="app-glass-head">
          <span class="app-glass-title">On the glass</span>
          <span class="apps-seg" role="group" aria-label="Preview size">
            <button type="button" data-scale="1" aria-pressed="${k === 1}">1×</button>
            <button type="button" data-scale="2" aria-pressed="${k === 2}">2×</button>
          </span>
        </div>
        <span class="tag-case" id="app-glass-case" style="--glass-w: ${152 * k}px; --glass-h: ${296 * k}px"><span class="glass">${live
    ? `<img data-preview="${shown}" alt="${esc(tag ? `What ${a.title} draws for ${tagName(tag)}` : `Preview of ${a.title}`)}">`
    : `<span class="app-glass-ico">${iconSvg(a)}</span>`}</span></span>
        <span class="app-glass-cap">${!live ? (a.disabled ? "Disabled: nothing drawn" : "Didn't load: nothing drawn")
    : tag ? `<code>${tag}</code>${tagInfo(tag).alias ? ` ${esc(tagInfo(tag).alias)}` : ""} · <span data-sent="${tag}"></span>`
      : "Preview · not on a tag"} · 152 × 296, 3 colours</span>
        ${live ? `<div class="app-glass-actions">
          ${tag ? `<button type="button" data-refresh="${tag}"
            title="Fetch fresh data, draw the screen again, and send it if it changed">Refresh now</button>`
    : '<button type="button" data-redraw title="Draw the preview again">Draw again</button>'}
          ${tag && a.has_on_open ? '<button type="button" data-open title="Runs what an NFC tap runs">Simulate NFC tap</button>' : ""}
        </div>` : ""}
      </aside>`;

    return `
      <div class="app-head">
        <div class="app-tile is-${s} app-head-ico" aria-hidden="true"><span class="app-ico">${iconSvg(a)}</span></div>
        <div class="app-head-text">
          <div class="app-head-title"><h2 id="app-title">${esc(a.title)}</h2>${statusPill(a)}</div>
          ${a.description ? `<p class="app-desc">${esc(a.description)}</p>` : ""}
        </div>
        <div class="app-actions">${actions.join("")}</div>
      </div>
      <div class="app-body">
        <div class="app-main">${main.join("")}</div>
        ${glass}
      </div>`;
  }

  function tagPanel(a, tag) {
    const fields = a.config_fields.map((f) => `
      <label>${esc(f.label)}
        <input name="${esc(f.key)}" type="text" spellcheck="false" placeholder="${esc(f.default)}">
      </label>`).join("");
    const controls = a.controls.map((c) => (c.kind === "button"
      ? `<button type="button" data-act="${esc(c.id)}">${esc(c.label)}</button>`
      : `<span class="app-text"><input type="text" data-text="${esc(c.id)}" maxlength="500"
           placeholder="${esc(c.placeholder || c.label)}" aria-label="${esc(c.label)}">
         <button type="button" data-send="${esc(c.id)}">${esc(c.label)}</button></span>`)).join("");
    const base = A.list.phone_base || "";
    const phone = `NFC link: <a href="${esc(base)}/tag/${tag}/view" target="_blank" rel="noopener"><code>${esc(base)}/tag/${tag}</code></a>` +
      (A.list.phone_base_local ? `<br>Only this computer can open it. Forward <code>/tag/</code> from a
        reverse proxy and enter its address under <a href="#settings">Settings</a>.` : "");
    return `
      <section class="app-tagpanel" aria-labelledby="app-tag-title">
        <div class="row">
          <h3 id="app-tag-title">On ${esc(tagLabel(tag))}</h3>
          <span class="grow"></span>
          <button type="button" data-stop="${tag}"
            title="The tag keeps its last picture until something else is sent">Stop on this tag</button>
        </div>
        <p id="app-msg" class="app-msg" role="status"></p>
        <div class="app-tagpanel-cols">
          ${fields ? `<form id="app-config" class="app-fields" novalidate>
            <h4>Settings for this tag</h4>${fields}
            <button type="submit">Save settings</button></form>` : ""}
          ${controls ? `<div class="app-controls">
            <h4>Try the phone page</h4>
            <div class="row">${controls}</div></div>` : ""}
        </div>
        <p class="hint">${phone}${A.list.phone_base_local ? "" : `
          <button type="button" data-nfc="${tag}"
            title="Write this link to the tag's NFC chip over the radio, at its next check-in. It is read back afterwards.">Write to the tag</button>`}</p>
      </section>`;
  }

  async function showCode(app) {
    const a = appOf(app);
    try {
      const src = await api(`/api/inkapps/source?app=${encodeURIComponent(app)}`);
      const files = src.files.map((f, i) => `<details class="tool" ${i === 0 ? "open" : ""}>
        <summary>${esc(f.name)}</summary><pre class="json wiz-code">${esc(f.text)}</pre></details>`).join("")
        || '<p class="hint">No text files in the folder.</p>';
      sheet(`<h3>The code of ${esc(a ? a.title : app)}</h3>
        <p class="hint">Read-only. Edit the files in <code>${esc(src.folder)}</code>, then press Reload apps.</p>
        <div class="apps-code">${files}</div>
        <div class="apps-sheet-actions"><button type="button" data-x>Close</button></div>`, () => {});
    } catch (err) {
      toast(err.message, true);
    }
  }

  const json = (value) => JSON.stringify(value, null, 2);

  function renderLive(a) {
    const tag = A.tag[a.id];
    for (const cell of document.querySelectorAll("#apps-page [data-sent]")) {
      const b = binding(cell.dataset.sent);
      cell.textContent = b && b.last_push_at ? `sent ${ageText(Date.now() / 1000 - b.last_push_at)} ago` : "not sent yet";
    }
    // previews, fetched again only when they could differ
    const imgs = [...document.querySelectorAll("#apps-page img[data-preview]")];
    for (const img of imgs) {
      const hex = img.dataset.preview;
      const b = binding(hex);
      const key = [a.id, hex, b && b.last_push_at, A.bump].join("|");
      const slot = `shot-${hex}`;
      if (A.previewKeys[slot] !== key) {
        A.previewKeys[slot] = key;
        img.src = `/api/inkapps/preview.png?app=${encodeURIComponent(a.id)}&tag=${hex}&v=${A.bump}-${Date.now()}`;
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

  // ── navigation ─────────────────────────────────────────────────────────────
  function openApp(id, fromRail) {
    if (fromRail && id === A.view) return;
    closeGroup();
    hideMenu();
    A.view = id;
    A.msg = null;
    A.data = null;
    A.log = [];
    A.shape = "";
    renderApps();
    const page = $("apps-page");
    page.classList.remove("enter", "swap");
    void page.offsetWidth;                // restart the slide-in
    page.classList.add(fromRail ? "swap" : "enter");
    $("apps-rail").querySelector(`[data-rail="${CSS.escape(id)}"]`)?.focus({ preventScroll: !fromRail });
    load();
  }

  function goHome() {
    const was = A.view;
    A.view = "";
    A.shape = "";
    renderApps();
    document.querySelector(`#apps-home .app-tile[data-key="${CSS.escape(was)}"]`)?.focus();
  }

  function activate(key) {
    const g = A.items.find((x) => isGroup(x) && x.id === key);
    if (g) openGroup(g);
    else openApp(key);
  }

  function openGroup(g, rename) {
    A.openGroup = g;
    $("apps-group").hidden = false;
    renderHome(false);
    const name = $("apps-group-name");
    if (rename) { name.focus(); name.select(); }
    else $("apps-group-grid").querySelector(".app-tile")?.focus();
  }

  function closeGroup() {
    if (!A.openGroup) return;
    const id = A.openGroup.id;
    A.openGroup = null;
    $("apps-group").hidden = true;
    document.querySelector(`#apps-grid .app-tile[data-key="${CSS.escape(id)}"]`)?.focus();
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
      const r = await api(path, body);
      if (r.result && r.state) {          // /api/tags/<hex>/...: the queue's answer
        A.msg = r.result.ok
          ? { text: "Queued. The tag's NFC chip gets this link at its next check-in, then it is read back.", bad: false }
          : { text: r.result.error || "Not queued.", bad: true };
      } else {
        A.msg = outcome(r);
      }
    } catch (err) {
      A.msg = { text: err.message, bad: true };
    }
    if (after) after();
    A.bump += 1;
    A.shape = "";             // rebuild: tags, settings and buttons may all have changed
    await load();
    return A.msg;
  }

  let toastTimer = 0;
  function toast(text, bad) {
    const t = $("apps-toast");
    t.textContent = text;
    t.classList.toggle("bad", Boolean(bad));
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 5000);
  }

  // A panel that slides up from the bottom: a question with its buttons.
  function sheet(html, onClick) {
    const box = $("apps-sheet");
    box.querySelector(".apps-sheet-body").innerHTML = html;
    box.hidden = false;
    box.onclick = (event) => {
      if (event.target === box || event.target.closest("[data-x]")) { closeSheet(); return; }
      onClick(event);
    };
    (box.querySelector(".primary, .danger") || box.querySelector("button"))?.focus();
  }
  function closeSheet() { $("apps-sheet").hidden = true; }

  function askRun(id) {
    const a = appOf(id);
    const free = A.list.tags.filter((t) => !a.tags.includes(t.id));
    if (!free.length) {
      toast(A.list.tags.length ? "Every tag the server knows already runs this app."
        : "No tags yet. A tag can be picked here once the hub has heard it.");
      return;
    }
    let pick = (free.find((t) => !ranBy(t.id)) || free[0]).id;
    const draw = () => sheet(`
      <h3>Run ${esc(a.title)}</h3>
      <p class="hint">Pick a tag. It shows the app after its next check-in.</p>
      <div class="apps-pick" role="radiogroup" aria-label="Tag">${free.map((t) => {
        const other = ranBy(t.id);
        const otherApp = other ? appOf(other) : null;
        return `<button type="button" class="apps-opt row" role="radio" data-pick="${t.id}" aria-checked="${t.id === pick}">
          <code>${t.id}</code><span>${esc(t.alias || "")}</span><span class="grow"></span>
          <span class="${other ? "apps-opt-warn" : "hint"}">${other ? `Replaces ${esc(otherApp ? otherApp.title : other)}` : "Free"}</span></button>`;
      }).join("")}</div>
      <div class="apps-sheet-actions"><button type="button" data-x>Cancel</button>
        <button type="button" class="primary" data-ok>Run on ${pick}</button></div>`, async (event) => {
      const p = event.target.closest("[data-pick]");
      if (p) { pick = p.dataset.pick; draw(); $("apps-sheet").querySelector(`[data-pick="${pick}"]`)?.focus(); return; }
      if (event.target.closest("[data-ok]")) {
        closeSheet();
        const r = await act(null, "/api/inkapps/bind", { tag: pick, app: id }, () => { A.tag[id] = pick; });
        if (!A.view) toast(r.bad ? r.text : `${a.title} on ${tagName(pick)}: ${r.text}`, r.bad);
      }
    });
    draw();
  }

  function askStop(id, only) {
    const a = appOf(id);
    const tags = only ? [only] : [...a.tags];
    sheet(`
      <h3>Stop ${esc(a.title)} on ${tags.length === 1 ? `tag ${tags[0]}` : plural(tags.length, "tag", "tags")}?</h3>
      <p class="hint">${esc(tags.map(tagName).join(", "))} keep${tags.length === 1 ? "s" : ""} the last picture until
        something else is sent. Settings and stored data stay.</p>
      <div class="apps-sheet-actions"><button type="button" data-x>Cancel</button>
        <button type="button" class="danger armed" data-ok>Stop</button></div>`, async (event) => {
      if (!event.target.closest("[data-ok]")) return;
      closeSheet();
      for (const hex of tags) await api("/api/inkapps/unbind", { tag: hex }).catch((err) => toast(err.message, true));
      A.msg = { text: `Stopped on ${tags.join(", ")}.`, bad: false };
      A.shape = "";
      await load();
    });
  }

  async function disable(id) {
    const title = appOf(id) ? appOf(id).title : id;
    try {
      const r = await api("/api/inkapps/disable", { app: id });
      if (!r.ok) throw new Error(r.error);
      A.items = A.items.filter((x) => x !== id);
      A.items.forEach((x) => { if (isGroup(x)) x.apps = x.apps.filter((k) => k !== id); });
      saveGrid();
      toast(`${title} is disabled. Its files and data are kept.`);
    } catch (err) {
      toast(err.message, true);
    }
    A.shape = "";
    await load();
  }

  function askDisable(id) {
    const a = appOf(id);
    if (!a.tags.length) { disable(id); return; }
    sheet(`
      <h3>Disable ${esc(a.title)}?</h3>
      <p class="hint">It stops on ${esc(a.tags.map(tagName).join(", "))}, and those tags keep their last
        picture. Its files, settings and stored data are kept, so you can enable it again later.</p>
      <div class="apps-sheet-actions"><button type="button" data-x>Cancel</button>
        <button type="button" class="danger armed" data-ok>Disable app</button></div>`, (event) => {
      if (event.target.closest("[data-ok]")) { closeSheet(); disable(id); }
    });
  }

  async function enable(id) {
    try {
      const r = await api("/api/inkapps/enable", { app: id });
      if (!r.ok) throw new Error(r.error);
      A.items = A.items.filter((x) => x !== id);
      A.items.push(id);
      saveGrid();
      A.fresh = id;
      setTimeout(() => { A.fresh = null; }, 1500);
      if (r.error) toast(`Enabled, but it did not load: ${r.error}`, true);
    } catch (err) {
      toast(err.message, true);
    }
    A.shape = "";
    await load();
  }

  function takeOutOfGroup(id) {
    const g = A.items.find((x) => isGroup(x) && x.apps.includes(id));
    if (!g) return;
    g.apps = g.apps.filter((k) => k !== id);
    A.items.splice(A.items.indexOf(g) + 1, 0, id);
    saveGrid();
    renderHome(true);
  }

  // ── the context menu ───────────────────────────────────────────────────────
  function showMenu(key, x, y) {
    const menu = $("apps-menu");
    const g = A.items.find((it) => isGroup(it) && it.id === key);
    const item = (cmd, label, cls = "") => `<button type="button" role="menuitem" data-m="${cmd}" class="${cls}">${label}</button>`;
    let html;
    if (g) {
      html = item("open", "Open group") + item("rename", "Rename") + "<hr>" + item("ungroup", "Ungroup");
    } else {
      const a = appOf(key);
      if (!a) return;
      if (a.disabled) {
        html = item("open", "Open") + item("enable", "Enable app");
      } else {
        const inGroup = A.items.some((it) => isGroup(it) && it.apps.includes(key));
        html = item("open", "Open")
          + (a.error ? "" : item("run", a.tags.length ? "Run on another tag…" : "Start on a tag…"))
          + (a.tags.length ? item("stop", `Stop on ${a.tags.length === 1 ? `tag ${a.tags[0]}` : `all ${a.tags.length} tags`}`) : "")
          + (inGroup ? item("ungroup-app", "Remove from group") : "")
          + "<hr>" + item("disable", "Disable app", "danger-item");
      }
    }
    menu.innerHTML = html;
    menu.hidden = false;
    menu.style.left = `${Math.max(8, Math.min(x, innerWidth - menu.offsetWidth - 8))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, innerHeight - menu.offsetHeight - 8))}px`;
    menu.onclick = (event) => {
      const b = event.target.closest("[data-m]");
      if (!b) return;
      hideMenu();
      const cmd = b.dataset.m;
      if (cmd === "open") activate(key);
      else if (cmd === "rename") openGroup(g, true);
      else if (cmd === "ungroup") { A.items.splice(A.items.indexOf(g), 1, ...g.apps); saveGrid(); renderHome(true); }
      else if (cmd === "run") askRun(key);
      else if (cmd === "stop") askStop(key);
      else if (cmd === "ungroup-app") takeOutOfGroup(key);
      else if (cmd === "disable") askDisable(key);
      else if (cmd === "enable") enable(key);
    };
    menu.querySelector("button")?.focus();
  }
  function hideMenu() { $("apps-menu").hidden = true; }

  $("apps-menu").addEventListener("keydown", (event) => {
    const items = [...$("apps-menu").querySelectorAll("button")];
    const i = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      items[(i + (event.key === "ArrowDown" ? 1 : -1) + items.length) % items.length].focus();
    }
  });

  // ── dragging ───────────────────────────────────────────────────────────────
  const inside = (r, e, m = 0) => e.clientX >= r.left - m && e.clientX <= r.right + m
    && e.clientY >= r.top - m && e.clientY <= r.bottom + m;
  const listOf = (ctx) => (ctx === "group" ? A.openGroup.apps : A.items);

  $("apps").addEventListener("pointerdown", (event) => {
    if (!$("apps-menu").contains(event.target)) hideMenu();
    if (event.target === $("apps-group")) { closeGroup(); return; }
    const t = event.target.closest(".app-tile[data-ctx]");
    if (!t || event.button !== 0) return;
    A.press = { key: t.dataset.key, ctx: t.dataset.ctx, x: event.clientX, y: event.clientY, el: t };
    A.press.timer = setTimeout(() => {
      if (A.press && !A.drag) { showMenu(A.press.key, A.press.x, A.press.y); A.press = null; }
    }, HOLD_MS);
  });

  $("apps").addEventListener("contextmenu", (event) => {
    const t = event.target.closest(".app-tile[data-ctx]");
    if (!t) return;
    event.preventDefault();
    if (A.press) clearTimeout(A.press.timer);
    A.press = null;
    showMenu(t.dataset.key, event.clientX, event.clientY);
  });

  function startDrag(event) {
    const p = A.press;
    clearTimeout(p.timer);
    const r = p.el.getBoundingClientRect();
    const ghost = p.el.cloneNode(true);
    ghost.className += " app-ghost";
    ghost.removeAttribute("data-key");
    ghost.removeAttribute("tabindex");
    ghost.style.width = `${r.width}px`;
    document.body.appendChild(ghost);
    A.drag = { key: p.key, ctx: p.ctx, ox: event.clientX - r.left, oy: event.clientY - r.top,
      ghost, merge: null, toOff: false, toOn: false, moved: false };
    p.el.classList.add("lifting");
    document.body.classList.add("apps-dragging");
  }

  window.addEventListener("pointermove", (event) => {
    const p = A.press;
    if (p && !A.drag && Math.hypot(event.clientX - p.x, event.clientY - p.y) > 6) startDrag(event);
    const d = A.drag;
    if (!d) return;
    d.ghost.style.left = `${event.clientX - d.ox}px`;
    d.ghost.style.top = `${event.clientY - d.oy}px`;

    if (d.ctx === "off") {                              // a disabled app, dragged up
      d.toOn = inside($("apps-grid").getBoundingClientRect(), event, 6);
      $("apps-grid").classList.toggle("drop-on", d.toOn);
      return;
    }
    if (d.ctx === "group" && !inside($("apps-group-panel").getBoundingClientRect(), event, 10)) {
      const g = A.openGroup;                            // out of the group, into the grid
      g.apps = g.apps.filter((k) => k !== d.key);
      A.items.splice(A.items.indexOf(g) + 1, 0, d.key);
      d.ctx = "main";
      d.moved = true;
      A.openGroup = null;
      $("apps-group").hidden = true;
      tidy();
      renderHome(true);
      return;
    }
    const single = !A.items.some((x) => isGroup(x) && x.id === d.key);
    if (d.ctx === "main" && single) {
      d.toOff = inside($("apps-disabled").getBoundingClientRect(), event);
      $("apps-disabled").classList.toggle("drop-on", d.toOff);
      if (d.toOff) { setMerge(null); return; }
    }

    const box = $(d.ctx === "group" ? "apps-group-grid" : "apps-grid");
    const tiles = [...box.querySelectorAll(".app-tile[data-key]")].filter((t) => t.dataset.key !== d.key);
    let hit = null;
    let merge = null;
    for (const t of tiles) {
      if (!inside(t.getBoundingClientRect(), event)) continue;
      hit = t;
      const ico = t.querySelector(".app-ico").getBoundingClientRect();
      if (d.ctx === "main" && single && inside(ico, event, -6)) merge = t.dataset.key;
      break;
    }
    setMerge(merge, hit);
    if (merge) return;

    const list = listOf(d.ctx);
    const rest = list.filter((x) => keyOf(x) !== d.key);
    const me = list.find((x) => keyOf(x) === d.key);
    let at = rest.length;
    if (hit) {
      const r = hit.getBoundingClientRect();
      at = rest.findIndex((x) => keyOf(x) === hit.dataset.key) + (event.clientX < r.left + r.width / 2 ? 0 : 1);
    } else {
      for (const t of tiles) {
        const r = t.getBoundingClientRect();
        if (event.clientY < r.top || (event.clientY <= r.bottom && event.clientX < r.left + r.width / 2)) {
          at = rest.findIndex((x) => keyOf(x) === t.dataset.key);
          break;
        }
      }
    }
    const next = [...rest.slice(0, at), me, ...rest.slice(at)];
    if (next.map(keyOf).join("\n") !== list.map(keyOf).join("\n")) {
      list.splice(0, list.length, ...next);
      d.moved = true;
      renderHome(true);
    }
  });

  function setMerge(key, hit) {
    const d = A.drag;
    if (key === d.merge) return;
    document.querySelectorAll("#apps .merge").forEach((t) => t.classList.remove("merge"));
    d.merge = key;
    if (key && hit) hit.classList.add("merge");
  }

  function endDrag(cancel) {
    const d = A.drag;
    A.drag = null;
    d.ghost.remove();
    document.body.classList.remove("apps-dragging");
    $("apps-disabled").classList.remove("drop-on");
    $("apps-grid").classList.remove("drop-on");
    if (cancel) { A.homeShape = ""; renderApps(); return; }
    if (d.ctx === "off") {
      if (d.toOn) enable(d.key);
      else renderHome(true);
      return;
    }
    if (d.toOff) { renderHome(true); askDisable(d.key); return; }
    if (d.merge) {
      const target = A.items.find((x) => keyOf(x) === d.merge);
      A.items = A.items.filter((x) => x !== d.key);
      if (isGroup(target)) {
        target.apps.push(d.key);
        saveGrid();
        renderHome(true);
      } else {
        const g = { id: `g${Date.now().toString(36)}`, name: "New group", apps: [d.merge, d.key] };
        A.items[A.items.indexOf(d.merge)] = g;
        saveGrid();
        renderHome(true);
        openGroup(g, true);
      }
      return;
    }
    if (d.moved) saveGrid();
    renderHome(true);
  }

  window.addEventListener("pointerup", () => {
    const p = A.press;
    A.press = null;
    if (p) clearTimeout(p.timer);
    if (A.drag) endDrag(false);
    else if (p) activate(p.key);
  });
  window.addEventListener("pointercancel", () => {
    if (A.press) clearTimeout(A.press.timer);
    A.press = null;
    if (A.drag) endDrag(true);
  });

  // ── keyboard ───────────────────────────────────────────────────────────────
  document.addEventListener("keydown", (event) => {
    if (screen !== "apps") return;
    if (event.key === "Escape") {
      if (A.drag) { endDrag(true); return; }
      if (!$("apps-menu").hidden) { hideMenu(); return; }
      if (!$("apps-sheet").hidden) { closeSheet(); return; }
      if (!$("apps-wizard").hidden) { closeWizard(); return; }
      if (A.openGroup) { closeGroup(); return; }
      if (A.view && !event.target.closest("input, textarea")) goHome();
      return;
    }
    if (event.target.id === "apps-new-tile" && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      openWizard();
      return;
    }
    const t = event.target.closest?.(".app-tile[data-ctx]");
    if (!t) return;
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      activate(t.dataset.key);
    } else if (event.key === "ContextMenu" || (event.shiftKey && event.key === "F10")) {
      event.preventDefault();
      const r = t.getBoundingClientRect();
      showMenu(t.dataset.key, r.left + r.width / 2, r.top + r.height * 0.7);
    } else if (event.altKey && (event.key === "ArrowLeft" || event.key === "ArrowRight") && t.dataset.ctx !== "off") {
      event.preventDefault();
      const list = listOf(t.dataset.ctx);
      const i = list.findIndex((x) => keyOf(x) === t.dataset.key);
      const j = i + (event.key === "ArrowRight" ? 1 : -1);
      if (j < 0 || j >= list.length) return;
      [list[i], list[j]] = [list[j], list[i]];
      saveGrid();
      renderHome(true);
      document.querySelector(`#apps .app-tile[data-key="${CSS.escape(t.dataset.key)}"]`)?.focus();
    }
  });

  // ── the New app wizard ─────────────────────────────────────────────────────
  const STEPS = ["Name", "Start from", "Behaviour", "Review"];
  const TEMPLATES = {
    blank: { title: "Blank", text: "An empty screen to start from.", icon: "", fields: [], buttons: [], timer: 0, tap: false },
    counter: { title: "Message and counter", text: "Buttons on the phone page change what the tag shows.",
      icon: "message", fields: ["Greeting"], buttons: ["Press me"], timer: 0, tap: false },
    web: { title: "Data from the web", text: "Fetches something on a timer and shows it.",
      icon: "cloud", fields: ["Place"], buttons: [], timer: 30, tap: false },
    tap: { title: "Tap tracker", text: "Counts each NFC tap, like the pill tracker.",
      icon: "check", fields: [], buttons: [], timer: 0, tap: true },
  };
  let W = null;
  const slug = (s) => s.toLowerCase().normalize("NFKD").replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 32);

  function openWizard() {
    hideMenu();
    W = { step: 0, title: "", id: "", idTouched: false, description: "", icon: "", template: "blank",
      draw: "layout", timerOn: false, minutes: 30, tap: false, fields: [], buttons: [], err: "", files: null };
    $("apps-wizard").hidden = false;
    drawWizard();
    $("wiz-title")?.focus();
  }
  function closeWizard() { $("apps-wizard").hidden = true; $("apps-new")?.focus(); }

  function spec() {
    return { id: W.id, title: W.title.trim(), description: W.description.trim(), icon: W.icon, draw: W.draw,
      timer_minutes: W.timerOn ? W.minutes : 0, on_open: W.tap,
      fields: W.fields.filter((x) => x.trim()), buttons: W.buttons.filter((x) => x.trim()) };
  }

  function wizardError() {
    if (W.step === 0) {
      if (!W.title.trim()) return "Enter a name for the app.";
      if (!/^[a-z0-9][a-z0-9_-]{0,31}$/.test(W.id)) return "Use 1-32 lower-case letters, digits, - and _ for the folder.";
      if (appOf(W.id)) return `inkapps/${W.id}/ already exists. Pick another folder name.`;
    }
    if (W.step === 2 && W.timerOn && !(Number.isInteger(W.minutes) && W.minutes >= 1 && W.minutes <= 10080)) {
      return "Updates run every 1 to 10080 minutes.";
    }
    return "";
  }

  function listEditor(key, label, placeholder) {
    return `<fieldset class="wiz-list"><legend>${label}</legend>
      ${W[key].map((v, i) => `<div class="row"><input type="text" data-list="${key}" data-i="${i}" value="${esc(v)}"
          placeholder="${placeholder}" maxlength="60" aria-label="${label} ${i + 1}">
        <button type="button" class="quiet" data-del="${key}" data-i="${i}">Remove</button></div>`).join("")}
      <button type="button" data-add="${key}">Add</button></fieldset>`;
  }

  function drawWizard() {
    let body = "";
    if (W.step === 0) {
      const icons = Object.keys(A.icons || {});
      body = `
        <label class="wiz-field">Name<input type="text" id="wiz-title" value="${esc(W.title)}" maxlength="60" placeholder="Bin day"></label>
        <label class="wiz-field">Folder
          <span class="wiz-folder"><code>inkapps/</code><input type="text" id="wiz-id" value="${esc(W.id)}"
            maxlength="32" spellcheck="false" placeholder="bin_day"><code>/</code></span></label>
        <label class="wiz-field">Description<input type="text" id="wiz-desc" value="${esc(W.description)}" maxlength="200"
          placeholder="Which bin goes out this week."></label>
        <fieldset class="wiz-icons"><legend>Icon <span class="hint">the same pixel icons a layout can draw</span></legend>
          <button type="button" data-icon="" aria-pressed="${!W.icon}" title="No icon: the first letter" aria-label="No icon">
            ${iconSvg({ title: W.title || "A", icon: "" })}</button>
          ${icons.map((n) => `<button type="button" data-icon="${n}" aria-pressed="${n === W.icon}" title="${n}"
            aria-label="${n}">${iconSvg({ icon: n })}</button>`).join("")}
        </fieldset>`;
    } else if (W.step === 1) {
      body = `
        <fieldset class="wiz-cards"><legend>Template</legend>
          ${Object.entries(TEMPLATES).map(([k, t]) => `<button type="button" class="apps-opt" data-template="${k}"
            aria-pressed="${k === W.template}"><b>${t.title}</b><span class="hint">${t.text}</span></button>`).join("")}
        </fieldset>
        <fieldset class="wiz-cards one"><legend>How it draws the screen</legend>
          <button type="button" class="apps-opt" data-draw="layout" aria-pressed="${W.draw === "layout"}">
            <b>Layout file</b><span class="hint">layout.xml lays out the screen; Python only supplies the data.
            Easiest to change, and the layout playground can open it.</span></button>
          <button type="button" class="apps-opt" data-draw="python" aria-pressed="${W.draw === "python"}">
            <b>Python</b><span class="hint">Draw the screen yourself on a canvas.</span></button>
        </fieldset>`;
    } else if (W.step === 2) {
      body = `
        <label class="wiz-check"><input type="checkbox" id="wiz-timer" ${W.timerOn ? "checked" : ""}>
          Updates itself every <input type="number" id="wiz-minutes" min="1" max="10080" step="1" value="${W.minutes}"
            aria-label="Minutes between updates"> minutes</label>
        <p class="hint">Each update that changes the screen costs the tag battery, so pick the longest interval that works.</p>
        <label class="wiz-check"><input type="checkbox" id="wiz-tap" ${W.tap ? "checked" : ""}>
          Does something when a phone taps the tag</label>
        ${listEditor("fields", "Settings for each tag", "Postcode")}
        ${listEditor("buttons", "Buttons on the phone page", "Mark done")}`;
    } else {
      const f = W.files || {};
      body = `
        <div class="app-hero">
          <div class="app-tile is-idle is-big" aria-hidden="true"><span class="app-ico">${iconSvg({ title: W.title, icon: W.icon })}</span></div>
          <div class="app-hero-text"><h3>${esc(W.title)}</h3><p class="hint">${esc(W.description) || "No description"}</p></div>
        </div>
        <p class="hint">It writes <code>inkapps/${esc(W.id)}/</code> with ${Object.keys(f).map((n) => `<code>${n}</code>`).join(" and ")}.
          The app starts idle: run it on a tag from its page or its menu, then edit the files and press Reload apps.</p>
        ${Object.entries(f).map(([name, text]) => `<details class="tool" ${name === "app.py" ? "open" : ""}>
          <summary>${name}</summary><pre class="json wiz-code">${esc(text)}</pre></details>`).join("")}`;
    }
    $("apps-wizard-panel").innerHTML = `
      <div class="row wiz-head"><h2 id="wiz-heading">New app</h2><span class="grow"></span>
        <button type="button" class="quiet" data-x>Close</button></div>
      <ol class="wiz-steps">${STEPS.map((s, i) => `<li class="${i <= W.step ? "on" : ""}"
        ${i === W.step ? 'aria-current="step"' : ""}>${i + 1} · ${s}</li>`).join("")}</ol>
      <div class="wiz-body">${body}</div>
      <p class="warning wiz-err" id="wiz-err" role="alert">${esc(W.err)}</p>
      <div class="apps-sheet-actions">
        ${W.step ? '<button type="button" data-back>Back</button>' : '<button type="button" data-x>Cancel</button>'}
        <button type="button" class="primary" data-next>${W.step === 3 ? "Create app" : "Next"}</button></div>`;
  }

  $("apps-wizard").addEventListener("input", (event) => {
    const t = event.target;
    if (t.id === "wiz-title") {
      W.title = t.value;
      if (!W.idTouched) { W.id = slug(W.title); $("wiz-id").value = W.id; }
    } else if (t.id === "wiz-id") { W.id = t.value.trim(); W.idTouched = true; }
    else if (t.id === "wiz-desc") W.description = t.value;
    else if (t.id === "wiz-minutes") W.minutes = Number(t.value);
    else if (t.dataset.list) W[t.dataset.list][Number(t.dataset.i)] = t.value;
    W.err = "";
    $("wiz-err").textContent = "";
  });
  $("apps-wizard").addEventListener("change", (event) => {
    if (event.target.id === "wiz-timer") W.timerOn = event.target.checked;
    if (event.target.id === "wiz-tap") W.tap = event.target.checked;
  });
  $("apps-wizard").addEventListener("keydown", (event) => {
    if (event.key === "Enter" && event.target.matches("input[type=text], input[type=number]")) {
      event.preventDefault();
      $("apps-wizard-panel").querySelector("[data-next]")?.click();
    }
  });
  $("apps-wizard").addEventListener("click", async (event) => {
    const t = event.target;
    if (t === $("apps-wizard") || t.closest("[data-x]")) { closeWizard(); return; }
    const pick = (attr) => t.closest(`[${attr}]`);
    if (pick("data-icon")) { W.icon = pick("data-icon").dataset.icon; drawWizard(); return; }
    if (pick("data-template")) {
      const k = pick("data-template").dataset.template;
      const tp = TEMPLATES[k];
      Object.assign(W, { template: k, fields: [...tp.fields], buttons: [...tp.buttons], timerOn: Boolean(tp.timer),
        minutes: tp.timer || W.minutes, tap: tp.tap });
      if (!W.icon) W.icon = tp.icon;
      drawWizard();
      return;
    }
    if (pick("data-draw")) { W.draw = pick("data-draw").dataset.draw; drawWizard(); return; }
    if (pick("data-add")) {
      const key = pick("data-add").dataset.add;
      W[key].push("");
      drawWizard();
      const inputs = $("apps-wizard").querySelectorAll(`[data-list="${key}"]`);
      inputs[inputs.length - 1]?.focus();
      return;
    }
    if (pick("data-del")) { const b = pick("data-del"); W[b.dataset.del].splice(Number(b.dataset.i), 1); drawWizard(); return; }
    if (t.closest("[data-back]")) { W.step -= 1; W.err = ""; drawWizard(); return; }
    if (!t.closest("[data-next]")) return;

    W.err = wizardError();
    if (W.err) { $("wiz-err").textContent = W.err; return; }
    const button = t.closest("[data-next]");
    button.disabled = true;
    try {
      if (W.step === 2) {                        // the review shows what the server would write
        const r = await api("/api/inkapps/create", { ...spec(), dry_run: true });
        if (!r.ok) throw new Error(r.error);
        W.files = r.files;
      }
      if (W.step < 3) {
        W.step += 1;
        drawWizard();
        $("apps-wizard-panel").querySelector("[data-next]")?.focus();
        return;
      }
      const r = await api("/api/inkapps/create", spec());
      if (!r.ok) throw new Error(r.error);
      A.items.push(r.id);
      saveGrid();
      A.fresh = r.id;
      setTimeout(() => { A.fresh = null; }, 1500);
      closeWizard();
      toast(r.error ? `Created inkapps/${r.id}/, but it did not load: ${r.error}`
        : `Created inkapps/${r.id}/. Edit its files, then press Reload apps.`, Boolean(r.error));
      await load();
    } catch (err) {
      W.err = err.message;
      const e = $("wiz-err");
      if (e) e.textContent = W.err;
    } finally {
      button.disabled = false;
    }
  });

  // ── the rest of the controls ───────────────────────────────────────────────
  $("apps-group-name").addEventListener("input", (event) => {
    if (!A.openGroup) return;
    A.openGroup.name = event.target.value.trim() || "Group";
    saveGrid();
    $("apps-grid").innerHTML = A.items.map((x) => (isGroup(x) ? groupTile(x) : appTile(x, "main"))).join("") + NEW_TILE;
  });
  $("apps-group-name").addEventListener("keydown", (event) => {
    if (event.key === "Enter") { event.preventDefault(); $("apps-group-grid").querySelector(".app-tile")?.focus(); }
  });

  $("apps-sort-name").addEventListener("click", () => { A.sortBy = "name"; A.sortAsc = true; sortChanged(); });
  $("apps-sort-date").addEventListener("click", () => { A.sortBy = "date"; A.sortAsc = false; sortChanged(); });
  $("apps-sort-dir").addEventListener("click", () => { A.sortAsc = !A.sortAsc; sortChanged(); });
  function sortChanged() {
    store("apps.dis.sort", A.sortBy);
    store("apps.dis.asc", A.sortAsc ? "1" : "0");
    A.homeShape = "";
    renderApps();
  }

  $("apps-new").addEventListener("click", openWizard);
  $("apps-grid").addEventListener("click", (event) => {
    if (event.target.closest("#apps-new-tile")) openWizard();
  });

  $("apps-page").addEventListener("submit", (event) => {
    if (event.target.id !== "app-config") return;
    event.preventDefault();
    const config = {};
    for (const input of event.target.querySelectorAll("input[name]")) {
      if (input.value !== "") config[input.name] = input.value;   // empty: the app's default
    }
    act(event.target.querySelector("button"), "/api/inkapps/config", { tag: A.tag[A.view], config });
  });

  $("apps-rail").addEventListener("click", (event) => {
    const b = event.target.closest("button[data-rail]");
    if (b) openApp(b.dataset.rail, true);
  });
  $("apps-all").addEventListener("click", goHome);
  $("apps-rail").addEventListener("keydown", (event) => {
    const keys = { ArrowDown: 1, ArrowRight: 1, ArrowUp: -1, ArrowLeft: -1 };
    if (!(event.key in keys)) return;
    const all = [...$("apps-rail").querySelectorAll("button")];
    const i = all.indexOf(document.activeElement);
    if (i < 0) return;
    event.preventDefault();
    all[Math.max(0, Math.min(all.length - 1, i + keys[event.key]))].focus();
  });

  $("apps-page").addEventListener("click", (event) => {
    const b = event.target.closest("button");
    if (!b) return;
    const app = A.view;
    const tag = A.tag[app];
    if (b.id === "app-more") { const r = b.getBoundingClientRect(); showMenu(app, r.right - 200, r.bottom + 4); }
    else if (b.id === "app-stop-all") askStop(app);
    else if (b.id === "app-enable") enable(app);
    else if (b.matches("[data-run]")) askRun(app);
    else if (b.matches("[data-code]")) showCode(app);
    else if (b.dataset.scale) {
      A.scale = Number(b.dataset.scale);
      store("apps.glass.scale", String(A.scale));
      const box = $("app-glass-case");
      box.style.setProperty("--glass-w", `${152 * A.scale}px`);
      box.style.setProperty("--glass-h", `${296 * A.scale}px`);
      for (const x of b.parentElement.children) x.setAttribute("aria-pressed", x === b);
    } else if (b.matches("[data-redraw]")) {
      A.bump += 1;
      renderLive(appOf(app));
    }
    else if (b.matches("[data-edit]")) {
      const input = $("app-config")?.querySelector("input");
      input?.scrollIntoView({ block: "center", behavior: "smooth" });
      input?.focus({ preventScroll: true });
    }
    else if (b.dataset.pick) {
      A.tag[app] = b.dataset.pick;
      A.msg = null;
      renderApps();
    } else if (b.dataset.refresh) act(b, "/api/inkapps/refresh", { tag: b.dataset.refresh });
    else if (b.dataset.stop) askStop(app, b.dataset.stop);
    else if (b.dataset.act) act(b, "/api/inkapps/action", { tag, action: b.dataset.act });
    else if (b.dataset.send) {
      const input = b.parentElement.querySelector("[data-text]");
      act(b, "/api/inkapps/action", { tag, action: b.dataset.send, value: input.value });
    } else if (b.matches("[data-open]")) act(b, "/api/inkapps/open", { tag });
    else if (b.dataset.nfc) act(b, `/api/tags/${b.dataset.nfc}/nfc`, {});
  });

  $("apps-reload").addEventListener("click", async () => {
    const b = $("apps-reload");
    b.disabled = true;
    try {
      await api("/api/inkapps/reload", {});
      A.shape = "";
      A.homeShape = "";
      A.bump += 1;
      await load();
      toast("Apps reloaded.");
    } catch (err) {
      toast(err.message, true);
    } finally {
      b.disabled = false;
    }
  });

  window.renderApps = renderApps;
  window.appsShown = load;           // app.js calls this when the screen opens
  if (screen === "apps") load();     // the page was opened at #apps, before this file loaded
  setInterval(() => {
    if (screen === "apps" && !document.hidden && !A.drag) load();
  }, APPS_POLL_MS);
})();
