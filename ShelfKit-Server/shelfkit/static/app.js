"use strict";

/* ShelfKit-Server front end.
 *
 * Screens: Fleet (home), Editor, Queue, Logs, Stats, Hub, Console, Settings.
 * Everything the server knows arrives from /api/poll a few times a second; the
 * screens are pure views over that plus the log lines. Nothing here renders a
 * bitmap: the preview, queue history, stats and the fleet map are placeholders
 * until the bitmap/event store exists (see docs/web-interface-implementation.md).
 *
 * What is really wired today: the two serial panes, the tag list derived from
 * POLL lines, the image picker and the single-image push, plus every control
 * that talks to those (DTR, Reset, Clear, Copy/Save log, Send/Cancel).
 */

const POLL_MS = 200;          // console lines want to feel live
const MAX_DOM_LINES = 2000;
const ONLINE_WINDOW_S = 30;   // a tag heard this recently counts as online
const LOW_BATTERY_V = 2.5;    // below this the battery is close to done
const STATUS_RANK = { online: 0, pending: 1, alert: 2, offline: 3, unreachable: 4 };
const THEME_KEY = "shelfkit-theme";

const $ = (id) => document.getElementById(id);

const ui = {
  status: $("status"),
  nav: $("nav"),
  theme: $("theme-toggle"),
  consoleDot: $("console-dot"),
  screens: [...document.querySelectorAll(".screen")],

  fleetSearch: $("fleet-search"),
  fleetFilters: $("fleet-filters"),
  fleetRows: $("fleet-rows"),
  fleetAll: $("fleet-all"),
  fleetBulk: $("fleet-bulk"),
  fleetSelected: $("fleet-selected"),
  fleetEmpty: $("fleet-empty"),
  fleetSerial: $("fleet-serial"),
  fleetOpenSerial: $("fleet-open-serial"),
  fleetTable: $("fleet-table"),
  bulkPush: $("bulk-push"),
  bulkForget: $("bulk-forget"),
  fleetForgetStale: $("fleet-forget-stale"),

  editorTargets: $("editor-targets"),
  editorImage: $("editor-image"),
  editorTag: $("editor-tag"),
  editorBrowse: $("editor-browse"),
  editorRender: $("editor-render"),
  editorPush: $("editor-push"),
  editorCancel: $("editor-cancel"),
  editorProgress: $("editor-progress"),
  editorFit: $("editor-fit"),
  editorDither: $("editor-dither"),
  editorWarn: $("editor-warn"),
  editorInfo: $("editor-preview-info"),
  previewOriginal: $("preview-original"),
  previewDevice: $("preview-device"),
  previewSel: $("preview-sel"),
  previewZoom: $("preview-zoom"),
  previewOriginalHint: $("preview-original-hint"),
  previewDeviceHint: $("preview-device-hint"),
  previewZoomHint: $("preview-zoom-hint"),

  queueRows: $("queue-rows"),
  queueEmpty: $("queue-empty"),
  queueCancel: $("queue-cancel"),

  logsTag: $("logs-tag"),
  logsEvent: $("logs-event"),
  logsRows: $("logs-rows"),
  logsEmpty: $("logs-empty"),

  hubSerial: $("hub-serial"),
  hubTail: $("hub-tail"),
  hubConsoleLink: $("hub-console-link"),
  hubOpenSerial: $("hub-open-serial"),

  panes: $("panes"),
  copyLogs: $("copy-logs"),

  drawer: $("drawer"),
  drawerHex: $("drawer-hex"),
  drawerInfo: $("drawer-info"),
  drawerPush: $("drawer-push"),
  drawerClose: $("drawer-close"),
  drawerAlias: $("drawer-alias"),
  drawerNotes: $("drawer-notes"),
  drawerSave: $("drawer-save"),
  drawerNewId: $("drawer-newid"),
  drawerFw: $("drawer-fw"),
  drawerService: $("drawer-service"),
  drawerRead: $("drawer-read"),
  drawerReadStatus: $("drawer-read-status"),
  drawerReadInfo: $("drawer-read-info"),
  drawerReadFiles: $("drawer-read-files"),
  drawerReadBin: $("drawer-read-bin"),
  drawerReadTxt: $("drawer-read-txt"),
  drawerFwStatus: $("drawer-fw-status"),
  drawerFlash: $("drawer-flash"),
  drawerForget: $("drawer-forget"),
  drawerWipe: $("drawer-wipe"),
  drawerAssign: $("drawer-assign"),

  picker: $("picker"),
  pickerUp: $("picker-up"),
  pickerDir: $("picker-dir"),
  pickerList: $("picker-list"),
  pickerCancel: $("picker-cancel"),

  portOptions: $("port-options"),
  toasts: $("toasts"),
};

// ── global state ───────────────────────────────────────────────────────────
let state = null;                 // last /api/state
let screen = "fleet";
let busy = false;
let timer = null;

const panes = new Map();          // console panes: key -> view
const logs = new Map();           // key -> [{stamp, text}] retained lines
const lastSeq = new Map();        // key -> highest sequence number already shown
const events = [];                // {id, ts, hex, event, detail, count} from the server
const picked = new Set();         // fleet selection, hex strings
const cursorState = new Map();    // key -> "epoch:seq" for /api/poll
const replayed = new Set();       // panes whose retained history we have announced
let eventCursor = 0;              // newest event id the page has asked for
let newestEventId = 0;            // newest event id the page has shown
let fleetFilter = "all";
let fleetSearch = "";
let fleetSort = { key: "hex", dir: 1 };
let drawerHex = null;
const signatures = {};            // screen -> last render signature

// ── helpers ────────────────────────────────────────────────────────────────
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function getJSON(url) {
  const response = await fetch(url, { cache: "no-store" });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

async function postJSON(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
  return response.json();
}

function hex4(value) {
  return Number(value).toString(16).toUpperCase().padStart(4, "0");
}

function ageText(seconds) {
  if (seconds === null || seconds === undefined) return "—";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function say(text, kind) {
  ui.status.textContent = text;
  ui.status.className = "status" + (kind ? ` ${kind}` : "");
}

function toast(text, kind) {
  const node = el("div", `toast ${kind || ""}`, text);
  ui.toasts.append(node);
  setTimeout(() => node.remove(), 5000);
}

// ── theme ──────────────────────────────────────────────────────────────────
// The theme lives on <html data-theme="dark|light">, set before first paint by
// the inline script in index.html. Here we only switch it and remember it.
function currentTheme() {
  return document.documentElement.dataset.theme === "light" ? "light" : "dark";
}

function applyTheme(next, persist) {
  const theme = next === "light" ? "light" : "dark";
  document.documentElement.dataset.theme = theme;
  if (persist) {
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch (err) {
      /* storage disabled: the choice just will not survive the reload */
    }
  }
  // the button shows what you would switch to
  ui.theme.textContent = theme === "dark" ? "\u2600" : "\u263E";
  ui.theme.title = `Switch to the ${theme === "dark" ? "light" : "dark"} theme`;
  ui.theme.setAttribute("aria-label", ui.theme.title);
}

ui.theme.addEventListener("click", () => {
  applyTheme(currentTheme() === "light" ? "dark" : "light", true);
});

// ── routing ────────────────────────────────────────────────────────────────
function show(name) {
  if (!ui.screens.some((section) => section.dataset.screen === name)) name = "fleet";
  screen = name;
  for (const section of ui.screens) section.hidden = section.dataset.screen !== name;
  for (const tab of ui.nav.querySelectorAll(".tab")) {
    tab.classList.toggle("on", tab.dataset.screen === name);
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  draw();          // a screen that was skipped while hidden must render now
}

ui.nav.addEventListener("click", (event) => {
  const tab = event.target.closest(".tab");
  if (tab) show(tab.dataset.screen);
});

window.addEventListener("hashchange", () => show(location.hash.slice(1) || "fleet"));

// ── console panes (the original two-port view) ─────────────────────────────
function buildPane(pane) {
  const root = el("section", "pane");
  root.dataset.key = pane.key;
  root.innerHTML = `
    <div class="pane-head">
      <span class="pane-name"></span>
      <span class="pane-status"></span>
    </div>
    <div class="pane-controls">
      <input class="port" type="text" list="port-options" spellcheck="false"
             autocomplete="off" placeholder="COM4">
      <input class="baud" type="number" min="300" step="1" title="baud rate">
      <button class="toggle-open">Open</button>
      <button class="toggle-dtr" title="DTR is the BOOT pin; it holds where you put it">DTR</button>
      <button class="reset" title="Pulse the reset line (RTS) for a moment">Reset</button>
      <button class="clear" title="Clear this pane's log">Clear</button>
    </div>
    <div class="log" tabindex="0"></div>`;

  const view = {
    root,
    name: root.querySelector(".pane-name"),
    status: root.querySelector(".pane-status"),
    port: root.querySelector(".port"),
    baud: root.querySelector(".baud"),
    openBtn: root.querySelector(".toggle-open"),
    dtrBtn: root.querySelector(".toggle-dtr"),
    resetBtn: root.querySelector(".reset"),
    clearBtn: root.querySelector(".clear"),
    log: root.querySelector(".log"),
    epoch: pane.epoch,
    cursor: 0,
  };

  view.openBtn.addEventListener("click", () => {
    const verb = view.openBtn.textContent === "Close" ? "close" : "open";
    command(pane.key, verb, { port: view.port.value.trim(), baud: view.baud.value });
  });
  view.dtrBtn.addEventListener("click", () => command(pane.key, "toggle", { line: "dtr" }));
  view.resetBtn.addEventListener("click", () => command(pane.key, "reset"));
  view.clearBtn.addEventListener("click", () => {
    clearLog(pane.key);
    command(pane.key, "clear");
  });
  for (const field of [view.port, view.baud]) {
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter") view.openBtn.click();
    });
  }

  panes.set(pane.key, view);
  ui.panes.append(root);
  for (const row of logs.get(pane.key) || []) appendRow(view, row.stamp, row.text);
  return view;
}

async function command(key, action, body) {
  try {
    render(await postJSON(`/api/pane/${key}/${action}`, body));
  } catch (err) {
    toast(`command failed: ${err.message}`, "bad");
  }
}

function appendRow(view, stamp, text) {
  // Read the scroll position BEFORE appending: afterwards the content is taller
  // and the check would always say "not at the bottom", killing auto-scroll.
  const stick = view.log.scrollHeight - view.log.scrollTop - view.log.clientHeight < 40;
  const row = el("div", "ln");
  if (text.startsWith("#")) row.classList.add("note");
  else if (/FAILED|error|rejected|gave up|cancelled/i.test(text)) row.classList.add("bad");
  row.append(el("span", "t", stamp), el("span", "m", text));
  view.log.append(row);
  let excess = view.log.childElementCount - MAX_DOM_LINES;
  if (excess > 0) {
    for (const child of [...view.log.children]) {
      if (excess-- <= 0) break;
      child.remove();
    }
  }
  if (stick) view.log.scrollTop = view.log.scrollHeight;
}

function rememberLine(key, stamp, text) {
  if (!logs.has(key)) logs.set(key, []);
  const list = logs.get(key);
  list.push({ stamp, text });
  if (list.length > MAX_DOM_LINES) list.splice(0, list.length - MAX_DOM_LINES);
}

function clearLog(key) {
  logs.set(key, []);
  lastSeq.set(key, 0);
  const view = panes.get(key);
  if (view) view.log.innerHTML = "";
}

/** Split a batch of lines into console output and fleet events.
 *
 *  Sequence numbers are monotonic per pane, so a line already shown can never be
 *  shown again - whatever the server sends. That is deliberate: a cursor-format
 *  mistake once made the server replay its whole buffer on every poll and the
 *  console looked like it was re-printing itself. A server restart (sequence
 *  numbers starting over) is handled in tick() by the server's own cursor going
 *  backwards, which clears the pane first.
 *
 *  Events are not derived here any more: the server records them durably and
 *  hands them over with each poll, so the Logs screen survives a restart.
 */
function ingest(key, lines) {
  const view = panes.get(key);
  let last = lastSeq.get(key) || 0;
  for (const [seq, stamp, text] of lines) {
    if (seq <= last) continue;       // already shown: never print twice
    last = seq;
    rememberLine(key, stamp, text);
    if (view) appendRow(view, stamp, text);
  }
  lastSeq.set(key, last);
}

/** One durable event row: [id, unix time, hex id, kind, detail].
 *
 *  Ids come from the database and only ever grow, so an id we have already shown
 *  is a duplicate (a retried poll, say) and is dropped. Consecutive identical
 *  rows still collapse into xN, which is how the firmware collapses its own log.
 */
function addEvent(id, at, hexId, kind, detail) {
  if (id <= newestEventId) return;   // already have it
  newestEventId = id;
  const hex = hexId || "";
  const ts = new Date(at * 1000).toTimeString().slice(0, 8);
  const previous = events[events.length - 1];
  if (previous && !detail && !previous.detail && previous.hex === hex && previous.event === kind) {
    previous.count += 1;
    previous.ts = ts;
    previous.id = id;
    return;
  }
  events.push({ id, ts, hex, event: kind, detail: detail || "", count: 1 });
  if (events.length > 2000) events.shift();
}

// ── deriving the fleet ─────────────────────────────────────────────────────
function tagRows() {
  if (!state) return [];
  const info = state.tag_info || {};
  return (state.tags || []).map(([addr, count]) => {
    const hex = hex4(addr);
    const detail = info[String(addr)] || { count, seen: null, push: null };
    let status = detail.seen !== null && detail.seen <= ONLINE_WINDOW_S ? "online" : "offline";
    if (state.sending && Number(state.send_to) === Number(addr)) status = "pending";
    return {
      addr: Number(addr),
      hex,
      alias: detail.alias || null,
      notes: detail.notes || null,
      row: detail.row ?? null,
      col: detail.col ?? null,
      status,
      battery: detail.vdd ? detail.vdd.volts : null,
      batteryPct: detail.vdd ? detail.vdd.percent : null,
      seen: detail.seen,
      count: detail.count ?? count,
      push: detail.push || null,
    };
  });
}

function visibleRows() {
  let rows = tagRows();
  const needle = fleetSearch.trim().toLowerCase();
  if (needle) {
    rows = rows.filter(
      (row) => row.hex.toLowerCase().includes(needle) || (row.alias || "").toLowerCase().includes(needle),
    );
  }
  if (fleetFilter !== "all") rows = rows.filter((row) => row.status === fleetFilter);

  const { key, dir } = fleetSort;
  rows.sort((a, b) => {
    let result = 0;
    if (key === "hex") result = a.hex.localeCompare(b.hex);
    else if (key === "status") result = STATUS_RANK[a.status] - STATUS_RANK[b.status];
    else if (key === "battery") result = (a.battery ?? -1) - (b.battery ?? -1);
    else if (key === "seen") {
      // "last content" sorts by how recently something was pushed
      result = (a.push?.age ?? Infinity) - (b.push?.age ?? Infinity);
    } else result = a.hex.localeCompare(b.hex);
    return result * dir;
  });
  return rows;
}

function closedPanes() {
  return (state?.panes || []).filter((pane) => !pane.open).map((pane) => pane.name);
}

function renderFleet() {
  const rows = visibleRows();
  // The ages ("30s", "2m") move every poll. Signing them would rebuild the whole
  // table - and recreate every thumbnail, which reads as a flicker - several
  // times a second, so the time-derived fields go into the signature rounded to
  // the minute. Status (online/offline) changes on its own window and still signs.
  const signed = rows.map((row) => ({
    ...row,
    seen: row.seen == null ? null : Math.floor(row.seen / 60),
    push: row.push ? { ...row.push, age: Math.floor(row.push.age / 60) } : null,
  }));
  const signature = JSON.stringify([signed, fleetSort, [...picked].sort(), closedPanes()]);
  if (signatures.fleet === signature) return;
  signatures.fleet = signature;

  ui.fleetRows.innerHTML = "";
  ui.fleetEmpty.hidden = rows.length > 0;
  ui.fleetTable.hidden = rows.length === 0;

  // With no tags and no ports open, the empty table is not the useful message:
  // say what is actually missing and offer the button that fixes it.
  const closed = closedPanes();
  ui.fleetSerial.textContent = closed.length
    ? `serial: ${closed.join(", ")} ${closed.length === 1 ? "is" : "are"} closed`
    : "";
  ui.fleetOpenSerial.hidden = closed.length === 0;

  for (const row of rows) {
    const tr = el("tr");
    tr.classList.toggle("picked", picked.has(row.hex));

    const pickCell = el("td", "pick");
    const box = el("input");
    box.type = "checkbox";
    box.checked = picked.has(row.hex);
    box.addEventListener("change", () => {
      if (box.checked) picked.add(row.hex);
      else picked.delete(row.hex);
      signatures.fleet = null;
      renderFleet();
    });
    pickCell.append(box);

    const hexCell = el("td", "hex");
    const label = el("span", "tag-id", row.hex);
    label.title = "open this tag's details";
    hexCell.append(label);

    const aliasCell = row.alias ? el("td", null, row.alias) : el("td", "dim", "—");
    aliasCell.title = row.alias
      ? `${row.alias} — click the row to edit`
      : "no alias yet — click the row to add one";

    const statusCell = el("td");
    const wrap = el("span", "status-cell");
    wrap.append(el("span", `status-dot s-${row.status}`), el("span", null, row.status));
    statusCell.append(wrap);

    const batteryCell = el("td");
    if (row.battery != null) {
      const low = row.battery < LOW_BATTERY_V;
      const volts = row.battery.toFixed(2);
      const pct = row.batteryPct ?? 0;
      batteryCell.append(el("span", low ? "bad" : null, `${volts} V · ${pct}%`));
      batteryCell.title = low
        ? `supply ${volts} V, ${pct}% of a CR2450 - low`
        : `supply ${volts} V, ${pct}% of a CR2450`;
    } else {
      batteryCell.append(el("span", "dim", "—"));
      batteryCell.title = "no voltage reported yet (older firmware)";
    }

    const actionsCell = el("td", "actions");
    const editButton = el("button", "ghost", "Editor");
    editButton.title = "open the editor with this tag selected";
    editButton.addEventListener("click", (event) => {
      event.stopPropagation();          // the row click opens the drawer instead
      openEditorFor(row.hex);
    });
    actionsCell.append(editButton);

    const contentCell = el("td");
    const thumb = el("span", "thumb");
    if (row.push?.thumb) {
      // the frame that was pushed, straight from the render cache
      const img = el("img", "thumb-img");
      img.src = row.push.thumb;
      img.alt = row.push.name || "last pushed frame";
      img.title = `${row.push.name} (${ageText(row.push.age)} ago)`;
      thumb.append(img, el("span", null, `${ageText(row.push.age)} ago`));
    } else {
      thumb.append(el("span", "box"));
      if (row.push) {
        thumb.append(el("span", null, `${ageText(row.push.age)} ago`));
        thumb.title = row.push.name;
      } else {
        thumb.append(el("span", "dim", "nothing pushed yet"));
      }
    }
    contentCell.append(thumb);
    contentCell.title = row.push ? row.push.name : "no content pushed from this session";

    tr.append(pickCell, hexCell, aliasCell, statusCell, batteryCell, contentCell, actionsCell);
    tr.addEventListener("click", (event) => {
      if (event.target.closest("input, a")) return;
      openDrawer(row.hex);
    });
    ui.fleetRows.append(tr);
  }

  ui.fleetBulk.hidden = picked.size === 0;
  ui.fleetSelected.textContent = `${picked.size} selected`;
  ui.fleetAll.checked = rows.length > 0 && rows.every((row) => picked.has(row.hex));
  for (const th of ui.fleetTable.querySelectorAll("th[data-sort]")) {
    th.classList.toggle("sorted", th.dataset.sort === fleetSort.key);
  }
}

// ── drawer ─────────────────────────────────────────────────────────────────
/** The lowest unused id at or above 0x0100, to prefill the identity field. */
function nextFreeId() {
  const used = new Set((state?.tags || []).map(([addr]) => Number(addr)));
  let candidate = 0x0100;
  while (used.has(candidate)) candidate += 1;
  return hex4(candidate);
}

function openDrawer(hex) {
  // ids are four uppercase hex digits everywhere (hex4); normalise so a
  // lowercase caller cannot make renderDrawer miss its row
  drawerHex = String(hex).toUpperCase().padStart(4, "0");
  ui.drawer.hidden = false;
  renderDrawer();
}

function closeDrawer() {
  drawerHex = null;
  ui.drawer.hidden = true;
}

function renderDrawer() {
  if (!drawerHex) return;
  const row = tagRows().find((candidate) => candidate.hex === drawerHex);
  ui.drawerHex.textContent = drawerHex;
  ui.drawerInfo.innerHTML = "";
  const facts = [
    ["Alias", row?.alias || "—"],
    ["Status", row ? row.status : "unknown"],
    ["Last seen", row ? `${ageText(row.seen)} ago` : "—"],
    ["Announcements", row ? String(row.count) : "0"],
    ["Last content", row?.push ? `${row.push.name} · ${ageText(row.push.age)} ago` : "—"],
    ["Position", row?.row !== null && row?.row !== undefined ? `row ${row.row}, col ${row.col}` : "—"],
    ["Battery", "—"],
  ];
  for (const [key, value] of facts) {
    ui.drawerInfo.append(el("dt", null, key), el("dd", null, value));
  }
  // Never overwrite what the user is typing into.
  const active = document.activeElement;
  if (row) {
    if (active !== ui.drawerAlias) ui.drawerAlias.value = row.alias || "";
    if (active !== ui.drawerNotes) ui.drawerNotes.value = row.notes || "";
  }
  ui.drawerNewId.placeholder = nextFreeId() || "next free";

  const firmwares = (state?.firmware || []).filter((f) => f.ok);
  const wanted = firmwares.map((f) => f.path).join(",");
  if (signatures.drawerFw !== wanted) {
    signatures.drawerFw = wanted;
    const keep = ui.drawerFw.value;
    ui.drawerFw.innerHTML = "";
    if (!firmwares.length) {
      const option = el("option", null, "(no HEX in Release/ - build first)");
      option.value = "";
      ui.drawerFw.append(option);
    }
    for (const fw of firmwares) {
      const option = el("option", null, `${fw.name}  (${Math.round(fw.size / 1024)} kB)`);
      option.value = fw.path;
      ui.drawerFw.append(option);
    }
    if (keep && [...ui.drawerFw.options].some((option) => option.value === keep)) {
      ui.drawerFw.value = keep;
    }
  }
  const dump = state?.dump || {};
  const mine = dump.id === drawerHex;
  const caps = state?.hub_caps || {};
  const hubBlind = caps.dump === false;      // an older hub firmware
  ui.drawerRead.disabled = !!dump.active || !!state?.sending || hubBlind;
  ui.drawerRead.title = hubBlind
    ? "this hub firmware cannot forward read-back bytes: flash vusion-hub-*.hex"
    : "Read the metadata pages back over the radio";
  ui.drawerReadStatus.textContent =
    mine && dump.active
      ? `reading ${dump.have || 0}/${dump.length} B`
      : "";
  ui.drawerReadInfo.innerHTML = "";
  if (hubBlind) {
    ui.drawerReadInfo.append(el("div", "bad",
      "this hub is running older firmware: it relays the frames but drops their bytes. " +
      "Flash vusion-hub-*.hex, then reload this page."));
  }
  if (mine && Array.isArray(dump.summary)) {
    for (const line of dump.summary) ui.drawerReadInfo.append(el("div", null, line));
  }
  if (mine && dump.error) {
    ui.drawerReadInfo.append(el("div", "bad", dump.error));
  }
  const ready = mine && (dump.bin || dump.txt);
  ui.drawerReadFiles.hidden = !ready;
  if (ready) {
    ui.drawerReadBin.href = "/api/dump.bin";
    ui.drawerReadTxt.href = "/api/dump.txt";
    ui.drawerReadBin.download = dump.bin || "flash.bin";
    ui.drawerReadTxt.download = dump.txt || "flash.txt";
  }

  ui.drawerFlash.disabled = !!state?.sending;
  ui.drawerFwStatus.textContent = state?.sending && state.progress
    ? `${state.status} - frame ${state.progress}`
    : "";
  ui.drawerPush.onclick = () => openEditorFor(drawerHex);
}

async function saveDrawer() {
  if (!drawerHex) return;
  try {
    const result = await postJSON(`/api/tags/${drawerHex}`, {
      alias: ui.drawerAlias.value,
      notes: ui.drawerNotes.value,
    });
    render(result.state);
    toast(`${drawerHex} saved`, "ok");
  } catch (err) {
    toast(`cannot save ${drawerHex}: ${err.message}`, "bad");
  }
}

// A delete is irreversible, so the button arms itself first: click once and it
// asks, click again within a few seconds and it goes.
let armed = null;
let armedTimer = null;

function armForget(button, label, action) {
  if (armed === button) {
    disarmForget();
    action();
    return;
  }
  disarmForget();
  armed = button;
  button.dataset.label = label;
  button.textContent = "Really forget?";
  armedTimer = setTimeout(disarmForget, 4000);
}

function disarmForget() {
  if (armedTimer) clearTimeout(armedTimer);
  armedTimer = null;
  if (armed) {
    armed.textContent = armed.dataset.label || "Forget";
    armed = null;
  }
}

async function forget(path, body, what) {
  try {
    const payload = await postJSON(path, body);
    render(payload.state);
    const result = payload.result || {};
    const n = result.forgot || 0;
    if (n) toast(`forgot ${n} tag${n === 1 ? "" : "s"}`, "ok");
    else toast(`nothing to forget: ${what}`, "warn");
    return n;
  } catch (err) {
    toast(`cannot forget: ${err.message}`, "bad");
    return 0;
  }
}

async function readFlash() {
  if (!drawerHex) return;
  ui.drawerRead.disabled = true;
  try {
    // 0x3000 = OTA header + identity record + reserved sector: all metadata
    const payload = await postJSON(`/api/tags/${drawerHex}/read`,
      { start: 0, length: 0x3000 });
    render(payload.state);
    const result = payload.result || {};
    if (!result.ok) {
      toast(result.error || "the read did not start", "bad");
      ui.drawerRead.disabled = false;
    }
  } catch (err) {
    toast(`cannot read the flash: ${err.message}`, "bad");
    ui.drawerRead.disabled = false;
  }
}

async function serviceImage() {
  if (!drawerHex) return;
  ui.drawerService.disabled = true;
  try {
    const payload = await postJSON(`/api/tags/${drawerHex}/service`, {});
    render(payload.state);
    const result = payload.result || {};
    if (result.ok) toast(`service label for ${result.id} is on its way`, "ok");
    else toast(result.error || "the label was not sent", "bad");
  } catch (err) {
    toast(`cannot send the service image: ${err.message}`, "bad");
  } finally {
    ui.drawerService.disabled = false;
  }
}

async function flashFirmware() {
  if (!drawerHex) return;
  const path = ui.drawerFw.value;
  if (!path) {
    toast("build a firmware first: python ShelfKit-Firmware/Tooling/build-all.py", "bad");
    return;
  }
  ui.drawerFlash.disabled = true;
  try {
    const payload = await postJSON(`/api/tags/${drawerHex}/flash`, { path });
    render(payload.state);
    const result = payload.result || {};
    if (!result.ok) {
      toast(result.error || "the firmware was not sent", "bad");
      ui.drawerFlash.disabled = false;
      return;
    }
    toast(`${result.bytes} bytes -> ${drawerHex}, entry ${result.entry}`, "ok");
  } catch (err) {
    toast(`cannot flash: ${err.message}`, "bad");
    ui.drawerFlash.disabled = false;
  }
}

async function assignId() {
  if (!drawerHex) return;
  const wanted = ui.drawerNewId.value.trim();
  ui.drawerAssign.disabled = true;
  try {
    const payload = await postJSON(`/api/tags/${drawerHex}/assign`, { id: wanted });
    render(payload.state);
    const result = payload.result || {};
    if (result.ok) {
      toast(`${drawerHex} is now ${result.id}`, "ok");
      ui.drawerNewId.value = "";
      drawerHex = result.id;          // the row moved; keep following this tag
      renderDrawer();
    } else {
      toast(result.error || "assignment failed", "bad");
    }
  } catch (err) {
    toast(`cannot assign an id: ${err.message}`, "bad");
  } finally {
    ui.drawerAssign.disabled = false;
  }
}

// ── editor ─────────────────────────────────────────────────────────────────
function editorTarget() {
  const value = Number(ui.editorTag.value);
  return Number.isFinite(value) && value > 0 ? value : null;
}

function openEditorFor(hex) {
  if (hex) {
    const addr = parseInt(hex, 16);
    if ([...ui.editorTag.options].some((option) => Number(option.value) === addr)) {
      ui.editorTag.value = String(addr);
    }
  }
  closeDrawer();
  show("editor");
}

function renderEditor() {
  const rows = tagRows();
  const options = rows.map((row) => `${row.hex}|${row.addr}`).join(",");
  if (signatures.editorOptions !== options) {
    signatures.editorOptions = options;
    const keep = ui.editorTag.value;
    ui.editorTag.innerHTML = "";
    if (!rows.length) {
      const option = el("option", null, "(no tag heard yet)");
      option.value = "";
      ui.editorTag.append(option);
    }
    for (const row of rows) {
      const option = el("option", null, `${row.hex}  (${row.count} polls)`);
      option.value = String(row.addr);
      ui.editorTag.append(option);
    }
    if (keep && [...ui.editorTag.options].some((option) => option.value === keep)) {
      ui.editorTag.value = keep;
    }
  }

  ui.editorImage.value = state?.image ? state.image.name || state.image.path : "";
  ui.editorImage.title = state?.image ? state.image.path : "";
  const target = editorTarget();
  ui.editorTargets.textContent = target ? `target ${hex4(target)}` : "no target";

  const editor = state?.editor;
  if (editor) {
    if (document.activeElement !== ui.editorFit && editor.fit) ui.editorFit.value = editor.fit;
    if (document.activeElement !== ui.editorDither && editor.dither) {
      ui.editorDither.value = editor.dither;
    }
    const preview = editor.preview || null;
    const key = preview ? preview.key : "";
    if (key !== lastPreviewKey) {          // only redraw when the frame changed
      lastPreviewKey = key;
      showPreview(preview);
    }
  }

  const sending = !!state?.sending;
  // Spec rule: no push without a rendered preview on screen.
  const ready = !!state?.image && !!target && !!currentPreview && !sending;
  ui.editorPush.textContent = sending ? "Cancel" : `Push to 1 tag`;
  ui.editorPush.classList.toggle("cancel", sending);
  ui.editorPush.classList.toggle("primary", !sending);
  ui.editorPush.disabled = !sending && !ready;
  ui.editorPush.title = sending
    ? "Stop after the frame in flight"
    : !state?.image
      ? "Pick an image first"
      : !currentPreview
        ? "Render the preview first"
        : !target
          ? "Wait for a tag to announce itself"
          : `Send to ${hex4(target)} now`;
  ui.editorProgress.textContent = sending
    ? state.progress
      ? `frame ${state.progress}`
      : "starting…"
    : "";
}

// ── queue ──────────────────────────────────────────────────────────────────
function renderQueue() {
  const signature = JSON.stringify([state?.sending, state?.progress, state?.send_to, state?.image]);
  if (signatures.queue === signature) return;
  signatures.queue = signature;

  ui.queueRows.innerHTML = "";
  ui.queueEmpty.hidden = !!state?.sending;
  ui.queueCancel.disabled = !state?.sending;

  if (!state?.sending) return;
  const tr = el("tr");
  const cells = [
    "—",
    hex4(state.send_to),
    state.image ? state.image.name : "—",
    "sending",
    state.progress || "0",
    "now",
  ];
  cells.forEach((value, index) => {
    const td = el("td");
    if (index === 3) {
      const wrap = el("span", "status-cell");
      wrap.append(el("span", "status-dot s-pending"), el("span", null, value));
      td.append(wrap);
    } else if (index === 1) {
      td.className = "hex";
      td.textContent = value;
    } else {
      td.textContent = value;
    }
    tr.append(td);
  });
  ui.queueRows.append(tr);
}

// ── logs ───────────────────────────────────────────────────────────────────
function renderLogs() {
  const tagFilter = ui.logsTag.value;
  const eventFilter = ui.logsEvent.value;
  const signature = JSON.stringify([events.length, events.at(-1), tagFilter, eventFilter, state?.tags?.length]);
  if (signatures.logs === signature) return;
  signatures.logs = signature;

  // tag filter options follow the fleet
  const tagChips = (state?.tags || []).map(([addr]) => `${hex4(addr)}|${addr}`).join(",");
  if (signatures.logsTags !== tagChips) {
    signatures.logsTags = tagChips;
    const keep = ui.logsTag.value;
    ui.logsTag.innerHTML = "";
    const all = el("option", null, "all tags");
    all.value = "";
    ui.logsTag.append(all);
    for (const [addr] of state?.tags || []) {
      const option = el("option", null, hex4(addr));
      option.value = hex4(addr);
      ui.logsTag.append(option);
    }
    if (keep) ui.logsTag.value = keep;
  }

  const rows = events.filter(
    (row) => (!tagFilter || row.hex === tagFilter) && (!eventFilter || row.event === eventFilter),
  );
  ui.logsRows.innerHTML = "";
  ui.logsEmpty.hidden = rows.length > 0;
  for (const row of [...rows].reverse().slice(0, 500)) {
    const tr = el("tr");
    tr.append(
      el("td", null, row.ts),
      el("td", "hex", row.hex || "—"),
      el("td", "dim", "—"),
    );
    const eventCell = el("td");
    eventCell.append(el("span", null, row.event));
    if (row.detail) {
      const detail = el("span", "dim", ` ${row.detail}`);
      detail.title = row.detail;
      eventCell.append(detail);
    }
    tr.append(eventCell);
    tr.append(el("td", row.count > 1 ? "" : "dim", row.count > 1 ? `×${row.count}` : ""));
    ui.logsRows.append(tr);
  }
}

// ── hub ────────────────────────────────────────────────────────────────────
function renderHub() {
  const hubPane = state?.panes?.find((pane) => pane.key === state.hub) || state?.panes?.[0];
  const tail = (logs.get(state?.hub) || []).slice(-200);
  const signature = JSON.stringify([hubPane, tail.length, tail.at(-1)?.stamp]);
  if (signatures.hub === signature) return;
  signatures.hub = signature;

  ui.hubSerial.innerHTML = "";
  if (hubPane) {
    const facts = [
      ["Port", hubPane.port || "—"],
      ["State", hubPane.status],
      ["Baud", `${hubPane.baud} 8N1`],
      ["Lines", String(hubPane.lines)],
      ["DTR (BOOT)", hubPane.dtr ? "asserted" : "released"],
      ["RTS (RESET)", hubPane.rts ? "asserted" : "released"],
    ];
    for (const [key, value] of facts) ui.hubSerial.append(el("dt", null, key), el("dd", null, value));
    const closed = closedPanes();
    ui.hubOpenSerial.hidden = closed.length === 0;
    ui.hubOpenSerial.textContent = closed.length
      ? `Open ${closed.join(" and ")} in Console`
      : "Open the serial ports in Console";
  } else {
    ui.hubSerial.append(el("dt", null, "Port"), el("dd", "dim", "no pane"));
  }

  ui.hubTail.innerHTML = "";
  if (!tail.length) {
    ui.hubTail.append(el("div", "ln more", "nothing on the hub's UART yet"));
  } else {
    for (const row of tail) {
      const line = el("div", "ln");
      line.append(el("span", "t", row.stamp), el("span", "m", row.text));
      ui.hubTail.append(line);
    }
    ui.hubTail.scrollTop = ui.hubTail.scrollHeight;
  }
}

// ── console ────────────────────────────────────────────────────────────────
function renderConsole() {
  const active = document.activeElement;
  for (const pane of state?.panes || []) {
    const view = panes.get(pane.key) || buildPane(pane);
    const isHub = pane.key === state.hub;
    view.root.classList.toggle("hub", isHub);
    view.root.classList.toggle("tag", !isHub);
    view.name.innerHTML = "";
    view.name.append(pane.name);
    const badge = el("span", "badge", isHub ? "hub" : "tag");
    view.name.append(badge);
    if (active !== view.port) view.port.value = pane.port || "";
    if (active !== view.baud) view.baud.value = pane.baud;
    view.openBtn.textContent = pane.open ? "Close" : "Open";
    view.dtrBtn.classList.toggle("on", !!pane.dtr);
    view.dtrBtn.title = `DTR (BOOT pin) ${pane.dtr ? "asserted" : "released"}`;
    view.resetBtn.disabled = !pane.open;
    view.status.textContent = pane.status;
    view.status.className =
      "pane-status" + (pane.status.startsWith("error") ? " error" : pane.open ? " open" : "");
    if (isHub && pane.open) ui.consoleDot.hidden = false;
    else if (isHub) ui.consoleDot.hidden = true;
  }
}

// ── ports / status ─────────────────────────────────────────────────────────
function renderPorts(ports) {
  const signature = (ports || []).map(([device]) => device).join(",");
  if (ui.portOptions.dataset.signature === signature) return;
  ui.portOptions.dataset.signature = signature;
  ui.portOptions.innerHTML = "";
  for (const [device, description] of ports || []) {
    const option = el("option");
    option.value = device;
    option.label = description ? `${device} — ${description}` : device;
    ui.portOptions.append(option);
  }
}

function render(next) {
  state = next;
  if (!state) return;
  renderPorts(state.ports);
  say(state.status, state.sending ? "busy" : /^image sent/.test(state.status) ? "ok" : "");
  const hubPane = (state.panes || []).find((pane) => pane.key === state.hub);
  ui.consoleDot.hidden = !hubPane || !hubPane.open;
  draw();
}

function draw() {
  if (!state) return;
  if (screen === "fleet") renderFleet();
  else if (screen === "editor") renderEditor();
  else if (screen === "queue") renderQueue();
  else if (screen === "logs") renderLogs();
  else if (screen === "hub") renderHub();
  else if (screen === "console") renderConsole();
  if (drawerHex) renderDrawer();
}

// ── polling ────────────────────────────────────────────────────────────────
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(tick, POLL_MS);
}

async function tick() {
  if (busy) return schedule();
  busy = true;
  try {
    // NB: do not name this local "cursors" - that is the function below, and a
    // `const cursors = [...cursors()]` here hits the temporal dead zone.
    const query = cursorQuery();
    const data = await getJSON(`/api/poll?c=${encodeURIComponent(query)}&e=${eventCursor}`);
    for (const [key, part] of Object.entries(data.panes || {})) {
      const previousSeq = Number((cursorState.get(key) || "0:0").split(":")[1]) || 0;
      // Cleared in the page, or the server restarted and its sequence numbers
      // started over: either way what we are showing is stale.
      if (part.reset || part.cursor < previousSeq) clearLog(key);
      if (!replayed.has(key) && part.lines.length) {
        // First attach: the server hands back its retained buffer. Say so, or a
        // reload looks like the log repeating itself.
        replayed.add(key);
        const view = panes.get(key);
        if (view) view.log.append(el("div", "ln more", `# ---- attached, replaying ${part.lines.length} retained lines ----`));
      }
      ingest(key, part.lines);
      cursorState.set(key, `${part.epoch}:${part.cursor}`);
    }
    for (const row of data.events || []) addEvent(row[0], row[1], row[2], row[3], row[4]);
    if (typeof data.event_cursor === "number") eventCursor = data.event_cursor;
    render(data.state);
  } catch (err) {
    say(`server not reachable — retrying (${err.message})`, "bad");
  } finally {
    busy = false;
    schedule();
  }
}

// cursors as "key=epoch:seq"; lines are ingested globally, so they are tracked
// here rather than on the console views (which may not exist yet).
function cursorQuery() {
  const parts = [];
  for (const [key, value] of cursorState) parts.push(`${key}=${value}`);
  return parts.join(",");
}

// ── actions ────────────────────────────────────────────────────────────────
async function sendOrCancel() {
  if (state?.sending) {
    try {
      render(await postJSON("/api/cancel"));
      toast("cancelling after the current frame");
    } catch (err) {
      toast(`cancel failed: ${err.message}`, "bad");
    }
    return;
  }
  const target = editorTarget();
  if (!target) return toast("wait for a tag to announce itself", "bad");
  try {
    render(await postJSON("/api/send", { addr: target }));
    toast(`pushing to ${hex4(target)} …`);
  } catch (err) {
    toast(`send failed: ${err.message}`, "bad");
  }
}

async function copyLogs() {
  let text;
  try {
    const response = await fetch("/api/log", { cache: "no-store" });
    text = await response.text();
  } catch (err) {
    return toast(`cannot read the log: ${err.message}`, "bad");
  }
  const lines = text.split("\n").length - 1;
  if (!lines) return toast("nothing logged yet");
  try {
    await navigator.clipboard.writeText(text);
    return toast(`copied ${lines} lines`, "ok");
  } catch (err) {
    /* fall through */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  toast(ok ? `copied ${lines} lines` : `clipboard refused ${lines} lines`, ok ? "ok" : "bad");
}

// ── editor previews ────────────────────────────────────────────────────────
// The server renders; the page only displays PNGs. The device pane is the frame
// exactly as the panel will show it (black/white/red), and the zoom pane is a
// 4x viewport into the same PNG - same pixels, no re-dithering in the browser.
const ZOOM = 4;
let previewZoomCentre = null;   // {x, y} in panel pixels
let currentPreview = null;      // the preview the page is showing
let lastPreviewKey = null;      // its cache key, to avoid redrawing every poll
let pickerDir = "";
let pickerParent = null;

function showPreview(preview) {
  const has = !!preview;
  currentPreview = preview || null;
  for (const [img, hint, url] of [
    [ui.previewOriginal, ui.previewOriginalHint, has ? preview.original : ""],
    [ui.previewDevice, ui.previewDeviceHint, has ? preview.device : ""],
  ]) {
    if (has) {
      img.src = url;
      img.setAttribute("src", url);
    } else {
      img.removeAttribute("src");
      img.src = "";
    }
    img.hidden = !has;
    hint.hidden = has;
  }
  ui.previewZoomHint.hidden = has;
  if (!has) {
    ui.previewZoom.style.backgroundImage = "";
    ui.previewSel.hidden = true;
    previewZoomCentre = null;
  } else {
    // re-apply the last zoom, or the middle of the frame
    drawZoom(previewZoomCentre || { x: 152 / 2, y: 296 / 2 }, true);
  }

  const warn = Number(state?.editor?.midtone_warn || 0.4);
  if (has && preview.midtone > warn) {
    ui.editorWarn.hidden = false;
    ui.editorWarn.textContent =
      `${Math.round(preview.midtone * 100)}% of this image is midtone - dithering will look ` +
      "muddy on this panel. A flatter, higher-contrast source reads better.";
  } else {
    ui.editorWarn.hidden = true;
  }

  ui.editorInfo.textContent = has
    ? `${preview.source[0]}x${preview.source[1]}` +
      `${preview.angle ? ` - rotate ${preview.angle} deg -` : " -"}` +
      ` ${preview.fitted[0]}x${preview.fitted[1]}, ${preview.fit}, ${preview.dither}`
    : "";
}

async function renderPreview() {
  if (!state?.image) {
    showPreview(null);
    return;
  }
  ui.editorInfo.textContent = "rendering…";
  try {
    const result = await postJSON("/api/preview");
    if (!result.ok) {
      ui.editorInfo.textContent = result.error || "render failed";
      showPreview(null);
      return;
    }
    showPreview(result);
    if (state) state.editor.preview = result;
  } catch (err) {
    ui.editorInfo.textContent = `render failed: ${err.message}`;
    showPreview(null);
  }
}

/** client point -> panel pixel, for the drag on the device pane */
function panelPoint(event) {
  const rect = ui.previewDevice.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  const x = ((event.clientX - rect.left) / rect.width) * 152;
  const y = ((event.clientY - rect.top) / rect.height) * 296;
  return { x: Math.min(151, Math.max(0, x)), y: Math.min(295, Math.max(0, y)) };
}

function drawZoom(centre, force) {
  const src = ui.previewDevice.src || ui.previewDevice.getAttribute("src");
  if (!src) return;
  const box = ui.previewZoom.getBoundingClientRect();
  const width = box.width || 150;
  const height = box.height || 292;
  const scaledW = 152 * ZOOM;
  const scaledH = 296 * ZOOM;
  let left = centre.x * ZOOM - width / 2;
  let top = centre.y * ZOOM - height / 2;
  left = Math.min(Math.max(0, left), Math.max(0, scaledW - width));
  top = Math.min(Math.max(0, top), Math.max(0, scaledH - height));
  ui.previewZoom.style.backgroundImage = `url("${src}")`;
  ui.previewZoom.style.backgroundSize = `${scaledW}px ${scaledH}px`;
  ui.previewZoom.style.backgroundPosition = `${-left}px ${-top}px`;
  previewZoomCentre = centre;
  if (force) ui.previewZoom.dataset.zoom = String(ZOOM);
}

/** an overlay rectangle over the device pane, in its own client coordinates */
function drawSelection(from, to) {
  const host = (ui.previewDevice.parentElement || ui.previewDevice).getBoundingClientRect();
  if (!host.width || !host.height) return;
  const px = (p) => p.x / 152 * host.width;
  const py = (p) => p.y / 296 * host.height;
  ui.previewSel.hidden = false;
  ui.previewSel.style.left = `${Math.min(px(from), px(to))}px`;
  ui.previewSel.style.top = `${Math.min(py(from), py(to))}px`;
  ui.previewSel.style.width = `${Math.abs(px(to) - px(from))}px`;
  ui.previewSel.style.height = `${Math.abs(py(to) - py(from))}px`;
}

function joinPath(dir, name) {
  const separator = dir.includes("\\") && !dir.includes("/") ? "\\" : "/";
  return dir.endsWith(separator) ? dir + name : dir + separator + name;
}

function sizeText(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${bytes} B`;
}

function pickerRow(icon, name, size, onClick) {
  const row = el("div", "row-item");
  if (!onClick) row.classList.add("empty");
  row.append(el("span", "icon", icon), el("span", "name", name));
  if (size) row.append(el("span", "size", size));
  if (onClick) row.addEventListener("click", onClick);
  return row;
}

async function loadDir(dir) {
  let data;
  try {
    data = await getJSON(`/api/files?dir=${encodeURIComponent(dir || "")}`);
  } catch (err) {
    return toast(`cannot list ${dir || "the image folder"}: ${err.message}`, "bad");
  }
  pickerDir = data.dir;
  pickerParent = data.parent;
  ui.pickerDir.textContent = data.dir;
  ui.pickerDir.title = data.dir;
  ui.pickerUp.disabled = !data.parent;
  ui.pickerList.innerHTML = "";
  if (!data.dirs.length && !data.files.length) {
    ui.pickerList.append(pickerRow("", "nothing here", ""));
  }
  for (const name of data.dirs) {
    ui.pickerList.append(pickerRow("▸", `${name}/`, "", () => loadDir(joinPath(pickerDir, name))));
  }
  for (const file of data.files) {
    ui.pickerList.append(
      pickerRow("·", file.name, sizeText(file.size), () => chooseImage(joinPath(pickerDir, file.name))),
    );
  }
}

async function chooseImage(path) {
  try {
    render(await postJSON("/api/image", { path }));
    ui.picker.hidden = true;
    toast(`image: ${path.split(/[\\/]/).pop()}`);
    await renderPreview();          // spec: never a push without a preview shown
  } catch (err) {
    toast(`cannot use that image: ${err.message}`, "bad");
  }
}

// ── wiring ─────────────────────────────────────────────────────────────────
ui.editorPush.addEventListener("click", sendOrCancel);
ui.editorCancel.addEventListener("click", () => show("fleet"));
ui.editorBrowse.addEventListener("click", () => {
  ui.picker.hidden = false;
  loadDir("");
});
ui.editorRender.addEventListener("click", renderPreview);
ui.editorTag.addEventListener("change", () => renderEditor());

async function setEditorOptions() {
  try {
    render(await postJSON("/api/editor", {
      fit: ui.editorFit.value,
      dither: ui.editorDither.value,
    }));
  } catch (err) {
    toast(`cannot set the render options: ${err.message}`, "bad");
    return;
  }
  await renderPreview();
}

ui.editorFit.addEventListener("change", setEditorOptions);
ui.editorDither.addEventListener("change", setEditorOptions);

// drag on the device pane -> the 4x viewport follows the drag
let dragFrom = null;

ui.previewDevice.addEventListener("pointerdown", (event) => {
  const point = panelPoint(event);
  if (!point) return;
  dragFrom = point;
  if (ui.previewDevice.setPointerCapture) ui.previewDevice.setPointerCapture(event.pointerId);
  drawSelection(point, point);
  if (event.preventDefault) event.preventDefault();
});

ui.previewDevice.addEventListener("pointermove", (event) => {
  if (!dragFrom) return;
  const point = panelPoint(event);
  if (!point) return;
  drawSelection(dragFrom, point);
  drawZoom({ x: (dragFrom.x + point.x) / 2, y: (dragFrom.y + point.y) / 2 }, false);
});

ui.previewDevice.addEventListener("pointerup", (event) => {
  if (!dragFrom) return;
  const point = panelPoint(event) || dragFrom;
  drawZoom({ x: (dragFrom.x + point.x) / 2, y: (dragFrom.y + point.y) / 2 }, true);
  ui.previewSel.hidden = true;
  dragFrom = null;
});

ui.previewDevice.addEventListener("pointercancel", () => {
  dragFrom = null;
  ui.previewSel.hidden = true;
});

window.addEventListener("resize", () => {
  if (previewZoomCentre) drawZoom(previewZoomCentre, true);
});

ui.fleetSearch.addEventListener("input", () => {
  fleetSearch = ui.fleetSearch.value;
  signatures.fleet = null;
  renderFleet();
});

ui.fleetFilters.addEventListener("click", (event) => {
  const chip = event.target.closest("button.chip");
  if (!chip) return;
  fleetFilter = chip.dataset.status;
  for (const other of ui.fleetFilters.querySelectorAll("button.chip")) {
    other.classList.toggle("on", other === chip);
  }
  signatures.fleet = null;
  renderFleet();
});

ui.fleetTable.querySelector("thead").addEventListener("click", (event) => {
  const th = event.target.closest("th[data-sort]");
  if (!th) return;
  const key = th.dataset.sort;
  fleetSort = { key, dir: fleetSort.key === key ? -fleetSort.dir : 1 };
  signatures.fleet = null;
  renderFleet();
});

ui.fleetAll.addEventListener("change", () => {
  const rows = visibleRows();
  if (ui.fleetAll.checked) rows.forEach((row) => picked.add(row.hex));
  else picked.clear();
  signatures.fleet = null;
  renderFleet();
});

ui.bulkPush.addEventListener("click", () => {
  if (picked.size > 1) toast("multi-target push is not implemented yet — using the first");
  const first = [...picked][0];
  if (first) openEditorFor(first);
});

ui.queueCancel.addEventListener("click", () => sendOrCancel());
ui.logsTag.addEventListener("change", () => {
  signatures.logs = null;
  renderLogs();
});
ui.logsEvent.addEventListener("change", () => {
  signatures.logs = null;
  renderLogs();
});

ui.hubConsoleLink.addEventListener("click", () => show("console"));
ui.hubOpenSerial.addEventListener("click", () => show("console"));
ui.fleetOpenSerial.addEventListener("click", () => show("console"));
ui.copyLogs.addEventListener("click", copyLogs);

ui.drawerClose.addEventListener("click", closeDrawer);
ui.drawerSave.addEventListener("click", saveDrawer);
ui.drawerAssign.addEventListener("click", assignId);
ui.drawerFlash.addEventListener("click", flashFirmware);
ui.drawerService.addEventListener("click", serviceImage);
ui.drawerRead.addEventListener("click", readFlash);
ui.drawerForget.addEventListener("click", () => {
  armForget(ui.drawerForget, "Forget tag", async () => {
    if (!drawerHex) return;
    const hex = drawerHex;
    if (await forget(`/api/tags/${hex}/forget`, {}, hex)) {
      closeDrawer();
    }
  });
});
ui.drawerWipe.addEventListener("click", () => {
  armForget(ui.drawerWipe, "Factory reset", async () => {
    if (!drawerHex) return;
    const hex = drawerHex;
    try {
      const payload = await postJSON(`/api/tags/${hex}/wipe`, {});
      render(payload.state);
      const result = payload.result || {};
      if (result.ok) {
        toast(`${hex} wiped, it comes back with a new id`, "ok");
        closeDrawer();
      } else {
        toast(result.error || "the tag was not reset", "bad");
      }
    } catch (err) {
      toast(`cannot reset the tag: ${err.message}`, "bad");
    }
  });
});
ui.bulkForget.addEventListener("click", () => {
  armForget(ui.bulkForget, "Forget", async () => {
    const addrs = [...picked];
    if (!addrs.length) return;
    if (await forget("/api/tags/forget", { addrs })) {
      picked.clear();
      render(state);
    }
  });
});
ui.fleetForgetStale.addEventListener("click", () => {
  armForget(ui.fleetForgetStale, "Forget silent", async () => {
    await forget("/api/tags/forget", { not_seen_for: 600 }, "silent tags");
  });
});
ui.pickerUp.addEventListener("click", () => pickerParent && loadDir(pickerParent));
ui.pickerCancel.addEventListener("click", () => (ui.picker.hidden = true));
ui.picker.addEventListener("click", (event) => {
  if (event.target === ui.picker) ui.picker.hidden = true;
});

document.addEventListener("keydown", (event) => {
  if (event.key !== "Escape") return;
  if (!ui.picker.hidden) ui.picker.hidden = true;
  else if (!ui.drawer.hidden) closeDrawer();
});

async function boot() {
  applyTheme(currentTheme(), false);   // sync the button with the theme already applied
  try {
    state = await getJSON("/api/state");
    for (const pane of state.panes) cursorState.set(pane.key, `${pane.epoch}:0`);
    show(location.hash.slice(1) || "fleet");
    schedule();
  } catch (err) {
    say(`cannot reach the server — is it still running? (${err.message})`, "bad");
    setTimeout(boot, 1000);
  }
}

boot();
