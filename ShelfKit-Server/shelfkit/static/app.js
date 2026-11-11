"use strict";

/* ShelfKit-Server front end. Plain JS, no build step.
 *
 * Screens: Fleet (home), Editor, Queue, Logs, Hub, plus a tag inspector that docks
 * over any of them. Everything the server knows arrives from /api/poll several
 * times a second and the screens are views over that. Lists update in place by key
 * (syncKeyed), so a poll never steals keyboard focus, closes a menu or reloads a
 * thumbnail. Nothing here renders a bitmap: the server renders, the page shows PNGs.
 */

const POLL_MS = 200;          // the console wants to feel live
const MAX_DOM_LINES = 2000;
// Tags check in every 120 s, back off to 300 s when idle and to 600 s on a weak link
// (SHELF_POLL_* in shelf_config.h). The thresholds below come from the Settings screen;
// these are only the values used until the first state arrives, and they match the
// server's defaults in shelfkit/prefs.py.
let prefs = {
  late_after_s: 330, silent_after_s: 630, forget_after_s: 900, low_battery_v: 2.5,
  fleet_view: "wall", wall_size: "full", axsdb_path: "",
  show_tag_port: true, hub_port: "", tag_port: "",
};
const THEME_KEY = "shelfkit-theme";

const STATUS_LABEL = {
  online: "Online", waiting: "Waiting", sending: "Sending", late: "Late", silent: "Silent",
};
const STATUS_RANK = { sending: 0, waiting: 1, online: 2, late: 3, silent: 4 };
const FILTERS = [
  ["all", "All"], ["online", "Online"], ["waiting", "Waiting"], ["late", "Late"],
  ["silent", "Silent"], ["alert", "Needs attention"],
];
const JOB_LABEL = {
  image: "Image", service: "Service label", firmware: "Firmware", id: "New ID",
  wipe: "Factory reset", read: "Flash read",
};
const JOB_STATE = {
  pending: "Waiting for the tag", running: "Running", done: "Done", failed: "Failed",
  cancelled: "Cancelled",
};
const JOB_MARK = {
  pending: "s-waiting", running: "s-sending", done: "s-online", failed: "s-alert",
  cancelled: "s-silent",
};
const FIT_TEXT = {
  cover: ["Cover", "Fills the panel and crops what overflows."],
  contain: ["Contain", "Shows the whole image, with paper around it."],
  stretch: ["Stretch", "Fills the panel and distorts the image."],
};
const DITHER_TEXT = {
  threshold: ["None", "Each pixel snaps to black, white or red. Best for text and logos."],
  "floyd-steinberg": ["Floyd-Steinberg", "Scatters pixels to suggest grey. Best for photos."],
  bayer4: ["Bayer 4×4", "A regular pattern that suggests grey. Best for gradients."],
};

const $ = (id) => document.getElementById(id);

// ── the panel's own lettering ──────────────────────────────────────────────
// A 5x7 bitmap font for tag IDs, so an ID looks like what the panel can print.
const GLYPHS = {
  0: "01110 10001 10011 10101 11001 10001 01110",
  1: "00100 01100 00100 00100 00100 00100 01110",
  2: "01110 10001 00001 00010 00100 01000 11111",
  3: "11111 00010 00100 00010 00001 10001 01110",
  4: "00010 00110 01010 10010 11111 00010 00010",
  5: "11111 10000 11110 00001 00001 10001 01110",
  6: "00110 01000 10000 11110 10001 10001 01110",
  7: "11111 00001 00010 00100 01000 01000 01000",
  8: "01110 10001 10001 01110 10001 10001 01110",
  9: "01110 10001 10001 01111 00001 00010 01100",
  A: "01110 10001 10001 11111 10001 10001 10001",
  B: "11110 10001 10001 11110 10001 10001 11110",
  C: "01110 10001 10000 10000 10000 10001 01110",
  D: "11100 10010 10001 10001 10001 10010 11100",
  E: "11111 10000 10000 11110 10000 10000 11111",
  F: "11111 10000 10000 11110 10000 10000 10000",
  H: "10001 10001 10001 11111 10001 10001 10001",
  I: "01110 00100 00100 00100 00100 00100 01110",
  K: "10001 10010 10100 11000 10100 10010 10001",
  L: "10000 10000 10000 10000 10000 10000 11111",
  S: "01111 10000 10000 01110 00001 00001 11110",
  T: "11111 00100 00100 00100 00100 00100 00100",
};

function pixelPath(text) {
  let path = "";
  [...text].forEach((char, index) => {
    const glyph = GLYPHS[char];
    if (!glyph) return;
    glyph.split(" ").forEach((bits, y) => {
      [...bits].forEach((bit, x) => {
        if (bit === "1") path += `M${index * 6 + x} ${y}h1v1h-1z`;
      });
    });
  });
  return path;
}

function pixelText(text, scale) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.classList.add("pixel");
  svg.setAttribute("role", "img");
  const path = document.createElementNS(ns, "path");
  svg.append(path);
  setPixelText(svg, text, scale);
  return svg;
}

function setPixelText(svg, text, scale) {
  if (svg.dataset.text === text && svg.dataset.scale === String(scale)) return;
  svg.dataset.text = text;
  svg.dataset.scale = String(scale);
  const width = text.length * 6 - 1;
  svg.setAttribute("viewBox", `0 0 ${width} 7`);
  svg.setAttribute("width", String(width * scale));
  svg.setAttribute("height", String(7 * scale));
  svg.setAttribute("aria-label", text);
  svg.firstChild.setAttribute("d", pixelPath(text));
}

// ── element references ─────────────────────────────────────────────────────
const ui = {
  status: $("status"),
  nav: $("nav"),
  navQueue: $("nav-queue"),
  theme: $("theme-toggle"),
  linkState: $("link-state"),
  linkMark: $("link-mark"),
  linkText: $("link-text"),
  transfer: $("transfer"),
  transferFill: $("transfer-fill"),
  screens: [...document.querySelectorAll(".screen")],

  fleetHeadline: $("fleet-headline"),
  fleetSubline: $("fleet-subline"),
  fleetOpenHub: $("fleet-open-hub"),
  fleetSearch: $("fleet-search"),
  fleetFilters: $("fleet-filters"),
  fleetView: $("fleet-view"),
  wallSize: $("wall-size"),
  fleetWall: $("fleet-wall"),
  fleetTableWrap: $("fleet-table-wrap"),
  fleetTable: $("fleet-table"),
  fleetRows: $("fleet-rows"),
  fleetAll: $("fleet-all"),
  fleetBulk: $("fleet-bulk"),
  fleetSelected: $("fleet-selected"),
  fleetEmpty: $("fleet-empty"),
  fleetNoMatch: $("fleet-nomatch"),
  fleetForgetStale: $("fleet-forget-stale"),
  bulkPush: $("bulk-push"),
  bulkService: $("bulk-service"),
  bulkForget: $("bulk-forget"),
  bulkClear: $("bulk-clear"),

  editorImage: $("editor-image"),
  editorBrowse: $("editor-browse"),
  editorRender: $("editor-render"),
  editorFit: $("editor-fit"),
  editorFitHint: $("editor-fit-hint"),
  editorDither: $("editor-dither"),
  editorDitherHint: $("editor-dither-hint"),
  editorTargets: $("editor-targets"),
  targetsOnline: $("targets-online"),
  targetsNone: $("targets-none"),
  editorEmpty: $("editor-empty"),
  editorWarn: $("editor-warn"),
  editorInfo: $("editor-preview-info"),
  editorPush: $("editor-push"),
  editorPushNote: $("editor-push-note"),
  previewOriginal: $("preview-original"),
  previewDevice: $("preview-device"),
  previewGlass: $("preview-glass"),
  previewSel: $("preview-sel"),
  previewZoom: $("preview-zoom"),

  queueWrap: $("queue-wrap"),
  queueRows: $("queue-rows"),
  queueEmpty: $("queue-empty"),
  queueCancel: $("queue-cancel"),

  logsWrap: $("logs-wrap"),
  logsTag: $("logs-tag"),
  logsEvent: $("logs-event"),
  logsSync: $("logs-sync"),
  logsRows: $("logs-rows"),
  logsEmpty: $("logs-empty"),

  panes: $("panes"),
  hubBanner: $("hub-banner"),
  hubCaps: $("hub-caps"),
  copyLogs: $("copy-logs"),
  displayWarning: $("display-warning"),
  displayEnabled: $("display-enabled"),
  displayTitle: $("display-title-input"),
  displayTimeout: $("display-timeout"),
  displayInterval: $("display-interval"),
  displayAlias: $("display-alias"),
  displayRefresh: $("display-refresh"),
  displayResult: $("display-result"),
  displayShown: $("display-shown"),

  inspector: $("inspector"),
  inspectorId: $("inspector-id"),
  inspectorAlias: $("inspector-alias"),
  inspectorClose: $("inspector-close"),
  inspectorGlass: $("inspector-glass"),
  inspectorFacts: $("inspector-facts"),
  inspectorAlert: $("inspector-alert"),
  inspectorPush: $("inspector-push"),
  inspectorService: $("inspector-service"),
  inspectorForm: $("inspector-form"),
  inspectorAliasInput: $("inspector-alias-input"),
  inspectorNotes: $("inspector-notes"),
  inspectorRow: $("inspector-row"),
  inspectorCol: $("inspector-col"),
  inspectorSave: $("inspector-save"),
  inspectorNewId: $("inspector-newid"),
  inspectorAssign: $("inspector-assign"),
  inspectorFw: $("inspector-fw"),
  inspectorFlash: $("inspector-flash"),
  inspectorFwStatus: $("inspector-fw-status"),
  inspectorRead: $("inspector-read"),
  inspectorReadStatus: $("inspector-read-status"),
  inspectorReadInfo: $("inspector-read-info"),
  inspectorReadFiles: $("inspector-read-files"),
  inspectorReadBin: $("inspector-read-bin"),
  inspectorReadTxt: $("inspector-read-txt"),
  inspectorForget: $("inspector-forget"),
  inspectorWipe: $("inspector-wipe"),

  setLate: $("set-late"),
  setSilent: $("set-silent"),
  setForget: $("set-forget"),
  setBattery: $("set-battery-v"),
  setView: $("set-view"),
  setSize: $("set-size"),
  settingsForm: $("settings-form"),
  settingsSave: $("settings-save"),
  settingsReset: $("settings-reset"),
  settingsNote: $("settings-note"),
  aliasesImport: $("aliases-import"),
  aliasesFile: $("aliases-file"),
  aliasesResult: $("aliases-result"),
  setHubPort: $("set-hub-port"),
  setTagPort: $("set-tag-port"),
  setShowTag: $("set-show-tag"),
  setAxsdb: $("set-axsdb"),
  setAxsdbState: $("set-axsdb-state"),

  navFlash: $("nav-flash"),
  flashForm: $("flash-form"),
  flashMethod: $("flash-method"),
  flashMethodHint: $("flash-method-hint"),
  flashFile: $("flash-file"),
  flashPane: $("flash-pane"),
  flashPaneField: $("flash-pane-field"),
  flashPartial: $("flash-partial"),
  flashPartialField: $("flash-partial-field"),
  flashWarning: $("flash-warning"),
  flashStart: $("flash-start"),
  flashCancel: $("flash-cancel"),
  flashResult: $("flash-result"),
  flashSub: $("flash-sub"),
  flashSteps: $("flash-steps"),
  flashError: $("flash-error"),
  flashLog: $("flash-log"),

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
const events = [];                // {id, at, hex, event, detail, count} from the server
const picked = new Set();         // fleet selection, hex strings
const targets = new Set();        // editor targets, hex strings
const cursorState = new Map();    // key -> "epoch:seq" for /api/poll
const replayed = new Set();       // panes whose retained history we have announced
const lastThumb = new Map();      // hex -> frame last seen on the wall (for the refresh)
let eventCursor = 0;              // newest event id the page has asked for
let newestEventId = 0;            // newest event id the page has shown
let fleetFilter = "all";
let fleetSearch = "";
let fleetSort = { key: "hex", dir: 1 };
let fleetView = prefs.fleet_view;
let wallSize = prefs.wall_size;
let prefsSignature = "";          // the server's prefs as last applied here
let inspected = null;             // hex of the open tag
let formDirty = false;            // the inspector form has unsaved typing
const signatures = {};

function stored(key, fallback) {
  try {
    return localStorage.getItem(key) || fallback;
  } catch (err) {
    return fallback;
  }
}

function store(key, value) {
  try {
    localStorage.setItem(key, value);
  } catch (err) {
    /* storage disabled: the choice just will not survive the reload */
  }
}

// ── helpers ────────────────────────────────────────────────────────────────
function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setText(node, text) {
  if (node.textContent !== text) node.textContent = text;
}

function setClass(node, cls) {
  if (node.className !== cls) node.className = cls;
}

/** Make parent's children match items, in order, reusing nodes by key. */
function syncKeyed(parent, items, keyOf, create, update) {
  const nodes = parent._nodes || (parent._nodes = new Map());
  const wanted = new Set();
  let cursor = parent.firstChild;
  for (const item of items) {
    const key = keyOf(item);
    wanted.add(key);
    let node = nodes.get(key);
    if (!node) {
      node = create(item);
      nodes.set(key, node);
    }
    update(node, item);
    if (node === cursor) cursor = cursor.nextSibling;
    else parent.insertBefore(node, cursor);
  }
  for (const [key, node] of nodes) {
    if (!wanted.has(key)) {
      node.remove();
      nodes.delete(key);
    }
  }
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
  if (seconds === null || seconds === undefined) return "never";
  if (seconds < 60) return `${Math.max(0, Math.round(seconds))} s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} h`;
  return `${Math.round(seconds / 86400)} d`;
}

function plural(count, word) {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function progressFraction(text) {
  const match = /^(\d+)\/(\d+)$/.exec(text || "");
  return match && Number(match[2]) ? Number(match[1]) / Number(match[2]) : null;
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
  if (persist) store(THEME_KEY, theme);
  // the button names what it will switch to
  ui.theme.textContent = theme === "dark" ? "Light" : "Dark";
  ui.theme.setAttribute("aria-label", `Switch to the ${ui.theme.textContent.toLowerCase()} theme`);
}

ui.theme.addEventListener("click", () => {
  applyTheme(currentTheme() === "light" ? "dark" : "light", true);
});

// ── routing ────────────────────────────────────────────────────────────────
function show(name) {
  if (name === "console") name = "hub";          // the console now lives on the Hub screen
  if (!ui.screens.some((section) => section.dataset.screen === name)) name = "fleet";
  screen = name;
  for (const section of ui.screens) section.hidden = section.dataset.screen !== name;
  for (const link of ui.nav.querySelectorAll("a")) {
    if (link.dataset.screen === name) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  window.scrollTo(0, 0);
  draw();
  if (name === "flash") refreshFlash();
  if (name === "hub") {
    // lines arrive while the screen is hidden, when a log has no height to scroll
    for (const view of panes.values()) view.log.scrollTop = view.log.scrollHeight;
  }
}

window.addEventListener("hashchange", () => show(location.hash.slice(1) || "fleet"));

// ── deriving the fleet ─────────────────────────────────────────────────────
function tagRows() {
  if (!state) return [];
  const info = state.tag_info || {};
  const jobs = state.queue || [];
  return (state.tags || []).map(([addr, count]) => {
    const hex = hex4(addr);
    const detail = info[String(addr)] || { count, seen: null, push: null };
    const mine = jobs.filter((job) => job.addr === hex);
    const seen = detail.seen;
    // whether the tag itself is checking in, whatever is queued for it
    const quiet = seen === null || seen > prefs.late_after_s;
    let status = "silent";
    if (seen !== null && seen <= prefs.late_after_s) status = "online";
    else if (seen !== null && seen <= prefs.silent_after_s) status = "late";
    if (mine.some((job) => job.state === "pending")) status = "waiting";
    if (mine.some((job) => job.state === "running")
        || (state.sending && Number(state.send_to) === Number(addr))) status = "sending";

    const volts = detail.vdd ? detail.vdd.volts : null;
    const low = volts !== null && volts < prefs.low_battery_v;
    const last = mine[mine.length - 1];
    const failed = last && last.state === "failed" ? last : null;
    let reason = null;
    if (failed) reason = `${JOB_LABEL[failed.kind] || failed.kind} failed`;
    else if (low) reason = "Battery low";

    return {
      addr: Number(addr),
      hex,
      alias: detail.alias || null,
      notes: detail.notes || null,
      row: detail.row ?? null,
      col: detail.col ?? null,
      status,
      quiet,
      alert: !!reason,
      reason,
      failed,
      low,
      battery: volts,
      batteryPct: detail.vdd ? detail.vdd.percent : null,
      fw: detail.fw || null,
      seen,
      count: detail.count ?? count,
      push: detail.push || null,
    };
  });
}

function matchesFilter(row, filter) {
  if (filter === "all") return true;
  if (filter === "alert") return row.alert;
  if (filter === "waiting") return row.status === "waiting" || row.status === "sending";
  return row.status === filter;
}

function visibleRows() {
  let rows = tagRows();
  const needle = fleetSearch.trim().toLowerCase();
  if (needle) {
    rows = rows.filter((row) => row.hex.toLowerCase().includes(needle)
      || (row.alias || "").toLowerCase().includes(needle)
      || (row.notes || "").toLowerCase().includes(needle));
  }
  rows = rows.filter((row) => matchesFilter(row, fleetFilter));

  const { key, dir } = fleetSort;
  const missing = (value) => value ?? Infinity;
  rows.sort((a, b) => {
    let result = 0;
    if (key === "alias") result = (a.alias || "￿").localeCompare(b.alias || "￿");
    else if (key === "status") result = STATUS_RANK[a.status] - STATUS_RANK[b.status];
    else if (key === "seen") result = missing(a.seen) - missing(b.seen);
    else if (key === "battery") result = (a.battery ?? -1) - (b.battery ?? -1);
    else if (key === "push") result = missing(a.push?.age) - missing(b.push?.age);
    else if (key === "shelf") {
      result = missing(a.row) - missing(b.row) || missing(a.col) - missing(b.col);
    }
    return (result || a.hex.localeCompare(b.hex)) * dir;
  });
  return rows;
}

function hubPane() {
  return (state?.panes || []).find((pane) => pane.key === state.hub) || state?.panes?.[0] || null;
}

// ── shared tag parts ───────────────────────────────────────────────────────
function statusWord(row) {
  return STATUS_LABEL[row.status];
}

function heardText(row) {
  return row.seen === null ? "Never heard" : `${ageText(row.seen)} ago`;
}

/** Fill a .glass element with the tag's frame, or its ID on blank paper. */
function paintGlass(glass, row, idScale) {
  const thumb = row?.push?.thumb || "";
  if (glass.dataset.thumb !== thumb || !glass.firstChild) {
    glass.dataset.thumb = thumb;
    glass.replaceChildren();
    if (thumb) {
      const img = el("img");
      img.src = thumb;
      img.alt = row.push.name || "The frame last pushed to this tag";
      glass.append(img);
    } else if (row) {
      const blank = el("span", "glass-blank");
      blank.append(pixelText(row.hex, idScale));
      blank.append(el("span", null, row.push ? row.push.name : "Nothing pushed yet"));
      glass.append(blank);
    }
  }
  let bar = glass.querySelector(".glass-sending");
  const sending = row?.status === "sending" && state?.progress;
  if (sending) {
    if (!bar) {
      bar = el("span", "glass-sending");
      glass.append(bar);
    }
    setText(bar, `Frame ${state.progress}`);
  } else if (bar) {
    bar.remove();
  }
}

function playRefresh(glass) {
  glass.classList.remove("refreshing");
  void glass.offsetWidth;            // restart the animation
  glass.classList.add("refreshing");
  setTimeout(() => glass.classList.remove("refreshing"), 1400);
}

function togglePicked(hex, on) {
  if (on) picked.add(hex);
  else picked.delete(hex);
  draw();
}

// ── fleet: the shelf wall ──────────────────────────────────────────────────
function createSlot(row) {
  const node = el("article", "slot");
  const stage = el("div", "slot-stage");
  const open = el("button", "tag-open");
  open.type = "button";
  const tagCase = el("span", "tag-case");
  const glass = el("span", "glass");
  tagCase.append(glass);
  open.append(tagCase);
  open.addEventListener("click", () => openInspector(row.hex));
  stage.append(open);

  const caption = el("div", "caption");
  const top = el("div", "caption-top");
  const box = el("input");
  box.type = "checkbox";
  box.setAttribute("aria-label", `Select tag ${row.hex}`);
  box.addEventListener("change", () => togglePicked(row.hex, box.checked));
  top.append(box, pixelText(row.hex, wallSize === "half" ? 1.5 : 2));
  const alias = el("div", "alias");
  const stateLine = el("div", "state-line");
  const mark = el("span");
  const word = el("span");
  stateLine.append(mark, word);
  const battery = el("div", "batt");
  caption.append(top, alias, stateLine, battery);
  node.append(stage, caption);
  node._parts = { open, glass, box, id: top.querySelector("svg"), alias, mark, word, battery };
  return node;
}

function paintBattery(node, row) {
  const volts = row.battery != null ? row.battery.toFixed(2) : "";
  const signature = `${volts}|${row.batteryPct}`;
  setClass(node, row.low ? "batt low" : "batt");
  if (node.dataset.sig === signature) return;
  node.dataset.sig = signature;
  node.replaceChildren();
  if (row.battery == null) {
    node.append(el("span", null, "No battery reading"));
    node.title = "This tag's firmware doesn't report its voltage";
    return;
  }
  const cell = el("span", "cell");
  const fill = el("i");
  fill.style.width = `${Math.max(0, Math.min(100, row.batteryPct ?? 0))}%`;
  cell.append(fill);
  node.append(cell, el("span", null, `${volts} V`));
  node.title = `${row.batteryPct ?? 0}% of a CR2450`;
}

function updateSlot(node, row) {
  const parts = node._parts;
  setClass(node, [
    "slot",
    row.status === "silent" ? "silent" : "",
    picked.has(row.hex) ? "picked" : "",
    inspected === row.hex ? "open" : "",
  ].filter(Boolean).join(" "));
  parts.box.checked = picked.has(row.hex);
  const half = wallSize === "half";
  setPixelText(parts.id, row.hex, half ? 1.5 : 2);
  paintGlass(parts.glass, row, half ? 2 : 4);

  const thumb = row.push?.thumb || "";
  if (lastThumb.has(row.hex) && lastThumb.get(row.hex) !== thumb && thumb) {
    playRefresh(parts.glass);
  }
  lastThumb.set(row.hex, thumb);

  setClass(parts.alias, row.alias ? "alias" : "alias none");
  setText(parts.alias, row.alias || "No alias");
  // a low battery has its own red line, so the state line keeps saying if the tag checks in
  setClass(parts.mark, `mark ${row.failed ? "s-alert" : `s-${row.status}`}`);
  setClass(parts.word, row.failed ? "reason" : "");
  setText(parts.word, row.failed ? row.reason : `${statusWord(row)}, ${heardText(row).toLowerCase()}`);
  parts.open.setAttribute("aria-label",
    `Tag ${row.hex}${row.alias ? `, ${row.alias}` : ""}. ${statusWord(row)}. Open details.`);
  paintBattery(parts.battery, row);
}

function renderWall(rows) {
  ui.fleetWall.classList.toggle("half", wallSize === "half");
  const shelves = new Map();
  for (const row of rows) {
    const key = row.row === null ? "none" : String(row.row);
    if (!shelves.has(key)) shelves.set(key, []);
    shelves.get(key).push(row);
  }
  const placed = [...shelves.keys()].filter((key) => key !== "none");
  const order = placed.sort((a, b) => Number(a) - Number(b));
  if (shelves.has("none")) order.push("none");

  syncKeyed(ui.fleetWall, order, (key) => key, (key) => {
    const shelf = el("section", "shelf");
    const title = el("h2");
    const row = el("div", "shelf-row");
    shelf.append(title, row);
    shelf._title = title;
    shelf._row = row;
    shelf.dataset.key = key;
    return shelf;
  }, (shelf, key) => {
    const list = shelves.get(key);
    // With no shelves set up the heading would only state the obvious.
    shelf._title.hidden = key === "none" && order.length === 1;
    setText(shelf._title, key === "none" ? "Not on a shelf" : `Shelf ${key}`);
    if (key !== "none") {
      list.sort((a, b) => (a.col ?? Infinity) - (b.col ?? Infinity) || a.hex.localeCompare(b.hex));
    }
    syncKeyed(shelf._row, list, (row) => row.hex, createSlot, updateSlot);
  });
}

// ── fleet: the table ───────────────────────────────────────────────────────
function createFleetRow(row) {
  const tr = el("tr");
  const pick = el("td", "pick");
  const box = el("input");
  box.type = "checkbox";
  box.setAttribute("aria-label", `Select tag ${row.hex}`);
  box.addEventListener("change", () => togglePicked(row.hex, box.checked));
  pick.append(box);

  const idCell = el("td");
  const link = el("button", "id-link");
  link.type = "button";
  link.append(pixelText(row.hex, 2));
  link.setAttribute("aria-label", `Open tag ${row.hex}`);
  idCell.append(link);

  const alias = el("td");
  const statusCell = el("td");
  const wrap = el("span", "status-cell");
  const mark = el("span");
  const word = el("span");
  wrap.append(mark, word);
  statusCell.append(wrap);
  const heard = el("td", "dim");
  const batteryCell = el("td");
  const battery = el("div", "batt");
  batteryCell.append(battery);
  const content = el("td");
  const thumb = el("div", "thumb");
  content.append(thumb);
  const shelf = el("td", "dim");

  tr.append(pick, idCell, alias, statusCell, heard, batteryCell, content, shelf);
  tr.addEventListener("click", (event) => {
    if (event.target.closest("input")) return;
    openInspector(row.hex);
  });
  tr._parts = { box, alias, mark, word, heard, battery, thumb, shelf };
  return tr;
}

function updateFleetRow(tr, row) {
  const parts = tr._parts;
  setClass(tr, [picked.has(row.hex) ? "picked" : "", inspected === row.hex ? "open" : ""]
    .filter(Boolean).join(" "));
  parts.box.checked = picked.has(row.hex);
  setClass(parts.alias, row.alias ? "" : "dim");
  setText(parts.alias, row.alias || "No alias");
  setClass(parts.mark, `mark ${row.failed ? "s-alert" : `s-${row.status}`}`);
  setClass(parts.word, row.failed ? "reason" : "");
  setText(parts.word, row.failed ? row.reason : statusWord(row));
  setText(parts.heard, heardText(row));
  paintBattery(parts.battery, row);

  const thumbUrl = row.push?.thumb || "";
  const signature = `${thumbUrl}|${row.push?.name || ""}`;
  if (parts.thumb.dataset.sig !== signature) {
    parts.thumb.dataset.sig = signature;
    parts.thumb.replaceChildren();
    if (thumbUrl) {
      const img = el("img", "thumb-img");
      img.src = thumbUrl;
      img.alt = "";
      parts.thumb.append(img);
    } else {
      parts.thumb.append(el("span", "thumb-img blank"));
    }
    const name = el("span", "thumb-name", row.push ? row.push.name : "Nothing pushed yet");
    if (!row.push) name.classList.add("dim");
    parts.thumb.append(name);
  }
  setText(parts.shelf, row.row === null ? "Not set" : `${row.row}, slot ${row.col ?? "not set"}`);
}

function renderTable(rows) {
  syncKeyed(ui.fleetRows, rows, (row) => row.hex, createFleetRow, updateFleetRow);
  ui.fleetAll.checked = rows.length > 0 && rows.every((row) => picked.has(row.hex));
  for (const th of ui.fleetTable.querySelectorAll("th[data-sort]")) {
    if (th.dataset.sort === fleetSort.key) {
      th.setAttribute("aria-sort", fleetSort.dir > 0 ? "ascending" : "descending");
    } else {
      th.removeAttribute("aria-sort");
    }
  }
}

// ── fleet: the screen ──────────────────────────────────────────────────────
function renderHeadline(all) {
  const hub = hubPane();
  const closed = hub && !hub.open;
  ui.fleetOpenHub.hidden = !closed;
  ui.fleetOpenHub.textContent = hub?.port ? `Open hub port ${hub.port}` : "Set up the hub port";

  if (closed) {
    setText(ui.fleetHeadline, "The hub port is closed");
    setClass(ui.fleetSubline, "subline");
    setText(ui.fleetSubline, all.length
      ? "These are the tags from the last session. No tag can check in until the port is open."
      : "Open it so the hub can hear your tags.");
    return;
  }
  if (!all.length) {
    setText(ui.fleetHeadline, "No tags heard yet");
    setClass(ui.fleetSubline, "subline");
    setText(ui.fleetSubline, "The hub is listening.");
    return;
  }
  const quiet = all.filter((row) => row.quiet).length;
  const checking = all.length - quiet;
  setText(ui.fleetHeadline, checking === all.length
    ? (all.length === 1 ? "Your tag is checking in" : `All ${all.length} tags are checking in`)
    : `${checking} of ${plural(all.length, "tag")} checking in`);

  const alerts = all.filter((row) => row.alert);
  const low = alerts.filter((row) => row.low).length;
  const failed = alerts.filter((row) => row.failed).length;
  const notes = [];
  if (failed) notes.push(`${plural(failed, "command")} failed`);
  if (low) notes.push(`${plural(low, "battery").replace("batterys", "batteries")} low`);
  const pending = (state.queue || []).filter((job) => job.state === "pending").length;
  if (notes.length) {
    setClass(ui.fleetSubline, "subline bad");
    setText(ui.fleetSubline, `${notes.join(", ")}.`);
  } else {
    setClass(ui.fleetSubline, "subline");
    setText(ui.fleetSubline, pending
      ? `${plural(pending, "command")} waiting for a tag to check in.`
      : "Nothing needs you right now.");
  }
}

function renderFilters(all) {
  const counts = FILTERS.map(([key]) => all.filter((row) => matchesFilter(row, key)).length);
  syncKeyed(ui.fleetFilters, FILTERS, ([key]) => key, ([key, label]) => {
    const button = el("button");
    button.type = "button";
    button.dataset.filter = key;
    button.append(el("span", null, label), el("span", "n"));
    return button;
  }, (button, [key]) => {
    const count = counts[FILTERS.findIndex(([name]) => name === key)];
    setText(button.lastChild, String(count));
    button.classList.toggle("on", fleetFilter === key);
    button.setAttribute("aria-pressed", String(fleetFilter === key));
  });
}

function renderFleet() {
  const all = tagRows();
  const rows = visibleRows();
  // drop selections of tags that have been forgotten or renamed
  for (const hex of [...picked]) {
    if (!all.some((row) => row.hex === hex)) picked.delete(hex);
  }
  renderHeadline(all);
  renderFilters(all);

  ui.fleetEmpty.hidden = all.length > 0;
  ui.fleetNoMatch.hidden = !(all.length > 0 && rows.length === 0);
  ui.fleetWall.hidden = fleetView !== "wall" || rows.length === 0;
  ui.fleetTableWrap.hidden = fleetView !== "table" || rows.length === 0;
  ui.wallSize.hidden = fleetView !== "wall";
  ui.fleetForgetStale.hidden = !all.some(
    (row) => row.seen === null || row.seen > prefs.forget_after_s);
  setText(ui.fleetForgetStale, `Forget tags silent for ${minutesText(prefs.forget_after_s)}`);
  for (const button of ui.fleetView.querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.view === fleetView);
  }
  for (const button of ui.wallSize.querySelectorAll("button")) {
    button.classList.toggle("on", button.dataset.size === wallSize);
  }

  if (fleetView === "wall") renderWall(rows);
  else renderTable(rows);

  ui.fleetBulk.hidden = picked.size === 0;
  setText(ui.fleetSelected, `${plural(picked.size, "tag")} selected`);
}

// ── inspector ──────────────────────────────────────────────────────────────
/** The lowest unused id at or above 0x0100, shown in the new-ID field. */
function nextFreeId() {
  const used = new Set((state?.tags || []).map(([addr]) => Number(addr)));
  let candidate = 0x0100;
  while (used.has(candidate)) candidate += 1;
  return hex4(candidate);
}

function loadForm(row) {
  ui.inspectorAliasInput.value = row?.alias || "";
  ui.inspectorNotes.value = row?.notes || "";
  ui.inspectorRow.value = row?.row ?? "";
  ui.inspectorCol.value = row?.col ?? "";
  setFormDirty(false);
}

function setFormDirty(dirty) {
  formDirty = dirty;
  ui.inspectorSave.disabled = !dirty;
}

function openInspector(hex) {
  const wanted = String(hex).toUpperCase().padStart(4, "0");
  if (inspected !== wanted) {
    inspected = wanted;
    disarm();
    loadForm(tagRows().find((row) => row.hex === wanted));
    vhist.tag = wanted;
    refreshVoltage();
  }
  ui.inspector.hidden = false;
  document.body.classList.add("inspecting");
  draw();
}

function closeInspector() {
  inspected = null;
  ui.inspector.hidden = true;
  document.body.classList.remove("inspecting");
  disarm();
  draw();
}

function renderInspector() {
  if (!inspected) return;
  const row = tagRows().find((candidate) => candidate.hex === inspected);
  if (!row) {                        // forgotten, or moved to a new id
    closeInspector();
    return;
  }

  if (!ui.inspectorId.firstChild) ui.inspectorId.append(pixelText(row.hex, 4));
  setPixelText(ui.inspectorId.firstChild, row.hex, 4);
  setClass(ui.inspectorAlias, row.alias ? "inspector-alias" : "inspector-alias none");
  setText(ui.inspectorAlias, row.alias || "No alias");
  paintGlass(ui.inspectorGlass, row, 4);

  const newest = (state?.firmware || []).find(
    (file) => file.ok && file.build && !/hub|bootloader/i.test(file.name));
  const reported = row.fw ? `${row.fw.version}-${row.fw.build}` : null;
  const outdated = reported && newest && newest.build !== reported;
  const facts = [
    ["Status", statusWord(row)],
    ["Heard", heardText(row)],
    ["Check-ins", String(row.count)],
    ["Battery", row.battery != null ? `${row.battery.toFixed(2)} V, ${row.batteryPct ?? 0}%` : "No reading", row.low],
    ["Firmware", row.fw
      ? `${row.fw.version}-${row.fw.build}${outdated ? `, Release/ has ${newest.build}` : newest ? ", up to date" : ""}`
      : "Not reported (tap the tag with a phone)", outdated],
    ["Power", row.fw ? `avg ${row.fw.avg_ua} \u00b5A, about ${row.fw.life_days} days on a CR2450` : "Not reported"],
    ["Reported", row.fw ? `${ageText(row.fw.age)} ago` : "Never"],
    ["Last push", row.push ? `${ageText(row.push.age)} ago` : "None"],
    ["Image", row.push ? row.push.name : "None"],
  ];
  const signature = JSON.stringify(facts);
  if (signatures.facts !== signature) {
    signatures.facts = signature;
    ui.inspectorFacts.replaceChildren();
    for (const [key, value, bad] of facts) {
      ui.inspectorFacts.append(el("dt", null, key), el("dd", bad ? "bad" : null, value));
    }
  }
  const alertText = row.failed
    ? `${row.reason}: ${row.failed.error || "see Logs for what happened."}`
    : row.low ? `The battery is at ${row.battery.toFixed(2)} V. Replace the CR2450 soon.` : "";
  ui.inspectorAlert.hidden = !alertText;
  setText(ui.inspectorAlert, alertText);

  // Unsaved typing wins over the poll. Otherwise show what the server holds.
  if (!formDirty) {
    const active = document.activeElement;
    for (const [input, value] of [
      [ui.inspectorAliasInput, row.alias || ""],
      [ui.inspectorNotes, row.notes || ""],
      [ui.inspectorRow, row.row ?? ""],
      [ui.inspectorCol, row.col ?? ""],
    ]) {
      if (input !== active && input.value !== String(value)) input.value = value;
    }
  }
  ui.inspectorNewId.placeholder = nextFreeId();

  // Only application images belong on a tag: a full bundle carries the bootloader,
  // and the hub and bootloader files are not tag applications at all.
  const firmwares = (state?.firmware || []).filter(
    (file) => file.ok && !/hub|bootloader/i.test(file.name));
  const wanted = firmwares.map((file) => file.path).join(",");
  if (signatures.inspectorFw !== wanted) {
    signatures.inspectorFw = wanted;
    const keep = ui.inspectorFw.value;
    ui.inspectorFw.replaceChildren();
    if (!firmwares.length) {
      const option = el("option", null, "No firmware in Release/");
      option.value = "";
      ui.inspectorFw.append(option);
    }
    for (const file of firmwares) {
      const stamp = file.build ? `, ${file.build}` : "";
      const option = el("option", null, `${file.name} (${Math.round(file.size / 1024)} kB${stamp})`);
      option.value = file.path;
      ui.inspectorFw.append(option);
    }
    if (keep && [...ui.inspectorFw.options].some((option) => option.value === keep)) {
      ui.inspectorFw.value = keep;
    }
  }
  ui.inspectorFlash.disabled = !firmwares.length;
  setText(ui.inspectorFwStatus, state?.sending && state.progress && row.status === "sending"
    ? `Frame ${state.progress}`
    : "");

  const dump = state?.dump || {};
  const mine = dump.id === inspected;
  const hubBlind = state?.hub_caps?.dump === false;      // an older hub firmware
  ui.inspectorRead.disabled = !!dump.active || hubBlind;
  setText(ui.inspectorReadStatus, mine && dump.active
    ? `Read ${dump.have || 0} of ${dump.length} bytes`
    : "");
  const lines = [];
  if (hubBlind) {
    lines.push(["bad", "This hub's firmware drops read-back data. Flash vusion-hub-latest.hex, then reload."]);
  }
  if (mine && Array.isArray(dump.summary)) lines.push(...dump.summary.map((line) => [null, line]));
  if (mine && dump.error) lines.push(["bad", dump.error]);
  const dumpSig = JSON.stringify(lines);
  if (signatures.dumpLines !== dumpSig) {
    signatures.dumpLines = dumpSig;
    ui.inspectorReadInfo.replaceChildren(...lines.map(([cls, text]) => el("div", cls, text)));
  }
  const ready = mine && (dump.bin || dump.txt);
  ui.inspectorReadFiles.hidden = !ready;
  if (ready) {
    ui.inspectorReadBin.href = "/api/dump.bin";
    ui.inspectorReadTxt.href = "/api/dump.txt";
    ui.inspectorReadBin.download = dump.bin || "flash.bin";
    ui.inspectorReadTxt.download = dump.txt || "flash.txt";
  }
}

async function saveInspector(event) {
  event.preventDefault();
  if (!inspected) return;
  const hex = inspected;
  try {
    const result = await postJSON(`/api/tags/${hex}`, {
      alias: ui.inspectorAliasInput.value,
      notes: ui.inspectorNotes.value,
      grid_row: ui.inspectorRow.value,
      grid_col: ui.inspectorCol.value,
    });
    setFormDirty(false);
    render(result.state);
    toast(`Saved ${hex}`);
  } catch (err) {
    toast(`Couldn't save ${hex}: ${err.message}`, "bad");
  }
}

/** Queue a command for one tag and report it in the page's words. */
async function queueCommand(hex, path, body, doneText, button) {
  if (button) button.disabled = true;
  try {
    const payload = await postJSON(`/api/tags/${hex}/${path}`, body || {});
    render(payload.state);
    const result = payload.result || {};
    if (result.ok) {
      toast(doneText);
      return true;
    }
    toast(result.error || `${hex} didn't accept that command`, "bad");
  } catch (err) {
    toast(`Couldn't queue that for ${hex}: ${err.message}`, "bad");
  } finally {
    if (button) button.disabled = false;
  }
  return false;
}

// A delete can't be undone, so the button arms itself first: press once and it
// asks, press again within a few seconds and it goes.
let armed = null;
let armedTimer = null;

function arm(button, question, action) {
  if (armed === button) {
    disarm();
    action();
    return;
  }
  disarm();
  armed = button;
  button.dataset.label = button.textContent;
  button.textContent = question;
  button.classList.add("armed");
  armedTimer = setTimeout(disarm, 4000);
}

function disarm() {
  if (armedTimer) clearTimeout(armedTimer);
  armedTimer = null;
  if (armed) {
    armed.textContent = armed.dataset.label;
    armed.classList.remove("armed");
    armed = null;
  }
}

async function forget(path, body) {
  try {
    const payload = await postJSON(path, body);
    render(payload.state);
    const count = payload.result?.forgot || 0;
    toast(count ? `Forgot ${plural(count, "tag")}` : "No tags matched, so nothing was forgotten");
    return count;
  } catch (err) {
    toast(`Couldn't forget: ${err.message}`, "bad");
    return 0;
  }
}

// ── editor ─────────────────────────────────────────────────────────────────
function openEditorFor(hexes) {
  if (hexes.length) {
    targets.clear();
    for (const hex of hexes) targets.add(hex);
  }
  closeInspector();
  location.hash = "#editor";
  show("editor");
}

function buildRadios(host, name, values, text, onChange) {
  if (host.dataset.built === values.join(",")) return;
  host.dataset.built = values.join(",");
  host.replaceChildren();
  for (const value of values) {
    const label = el("label");
    const input = el("input");
    input.type = "radio";
    input.name = name;
    input.value = value;
    input.addEventListener("change", onChange);
    label.append(input, el("span", null, text[value]?.[0] || value));
    host.append(label);
  }
}

function radioValue(host) {
  return host.querySelector("input:checked")?.value;
}

function setRadio(host, value) {
  const input = [...host.querySelectorAll("input")].find((item) => item.value === value);
  if (input && !input.checked) input.checked = true;
}

function renderEditor() {
  const editor = state?.editor;
  if (editor) {
    buildRadios(ui.editorFit, "fit", editor.fits || [], FIT_TEXT, setEditorOptions);
    buildRadios(ui.editorDither, "dither", editor.dithers || [], DITHER_TEXT, setEditorOptions);
    setRadio(ui.editorFit, editor.fit);
    setRadio(ui.editorDither, editor.dither);
    setText(ui.editorFitHint, FIT_TEXT[editor.fit]?.[1] || "");
    setText(ui.editorDitherHint, DITHER_TEXT[editor.dither]?.[1] || "");
    const preview = editor.preview || null;
    const key = preview ? preview.key : "";
    if (key !== lastPreviewKey) {          // only redraw when the frame changed
      lastPreviewKey = key;
      showPreview(preview);
    }
  }

  setClass(ui.editorImage, state?.image ? "filename" : "filename none");
  setText(ui.editorImage, state?.image ? state.image.name : "No image picked");
  ui.editorImage.title = state?.image ? state.image.path : "";
  ui.editorRender.hidden = !state?.image;

  const rows = tagRows();
  for (const hex of [...targets]) {
    if (!rows.some((row) => row.hex === hex)) targets.delete(hex);
  }
  if (rows.length === 1 && !signatures.autoTarget) {  // the only tag is the obvious target
    signatures.autoTarget = true;
    targets.add(rows[0].hex);
  }
  renderTargets(rows);

  const count = targets.size;
  const missing = !state?.image
    ? "Pick an image first."
    : !currentPreview
      ? "Waiting for the render."
      : !count
        ? (rows.length ? "Choose at least one tag." : "No tags to send to yet.")
        : "";
  ui.editorPush.disabled = !!missing || pushing;
  setText(ui.editorPush, count > 1 ? `Push to ${count} tags` : "Push image");
  setText(ui.editorPushNote, missing || (count === 1
    ? `Goes to ${[...targets][0]} when it next checks in.`
    : "Each tag receives it when it next checks in."));
}

function renderTargets(rows) {
  ui.targetsOnline.hidden = ui.targetsNone.hidden = !rows.length;
  const items = rows.length ? rows : [null];
  syncKeyed(ui.editorTargets, items, (row) => (row ? row.hex : "none"), (row) => {
    if (!row) return el("div", "none", "Tags appear here once the hub hears them.");
    const label = el("label", "target");
    const box = el("input");
    box.type = "checkbox";
    box.addEventListener("change", () => {
      if (box.checked) targets.add(row.hex);
      else targets.delete(row.hex);
      draw();
    });
    const alias = el("span", "alias");
    const mark = el("span");
    label.append(box, pixelText(row.hex, 2), alias, mark);
    label._parts = { box, alias, mark };
    return label;
  }, (label, row) => {
    if (!row) return;
    const parts = label._parts;
    parts.box.checked = targets.has(row.hex);
    setClass(parts.alias, row.alias ? "alias" : "alias none");
    setText(parts.alias, row.alias || "No alias");
    setClass(parts.mark, `mark ${row.failed ? "s-alert" : `s-${row.status}`}`);
    parts.mark.title = row.reason || statusWord(row);
  });
}

let pushing = false;

async function pushImage() {
  const hexes = [...targets];
  if (!hexes.length) return;
  pushing = true;
  ui.editorPush.disabled = true;
  let queued = 0;
  try {
    for (const hex of hexes) {
      const payload = await postJSON("/api/send", { addr: parseInt(hex, 16) });
      if (payload.result?.ok) queued += 1;
      else toast(`${hex}: ${payload.result?.error || "not queued"}`, "bad");
      render(payload.state);
    }
    if (queued) {
      toast(queued === 1
        ? `Queued for ${hexes[0]}. It goes out when the tag next checks in.`
        : `Queued for ${queued} tags. Each goes out when its tag next checks in.`);
    }
  } catch (err) {
    toast(`Couldn't queue the image: ${err.message}`, "bad");
  } finally {
    pushing = false;
    draw();
  }
}

// The server renders; the page only displays PNGs. The device pane is the frame
// exactly as the panel will show it, and the loupe is a 4x view of the same PNG:
// same pixels, no re-dithering in the browser.
const ZOOM = 4;
const PANEL_W = 152;
const PANEL_H = 296;
let loupeCentre = { x: PANEL_W / 2, y: PANEL_H / 2 };
let currentPreview = null;
let lastPreviewKey = null;

function showPreview(preview) {
  const has = !!preview;
  currentPreview = preview || null;
  for (const [img, url] of [
    [ui.previewOriginal, has ? preview.original : ""],
    [ui.previewDevice, has ? preview.device : ""],
  ]) {
    if (has) img.src = url;
    else img.removeAttribute("src");
    img.hidden = !has;
  }
  ui.editorEmpty.hidden = has;
  ui.previewSel.hidden = !has;
  if (has) {
    drawLoupe(loupeCentre);
  } else {
    ui.previewZoom.style.backgroundImage = "";
  }

  const warn = Number(state?.editor?.midtone_warn || 0.4);
  const muddy = has && preview.midtone > warn;
  ui.editorWarn.hidden = !muddy;
  setText(ui.editorWarn, muddy
    ? `${Math.round(preview.midtone * 100)}% of this image is midtone, so it will look muddy on `
      + "this panel. A flatter source with more contrast reads better."
    : "");
  setText(ui.editorInfo, has
    ? `Source ${preview.source[0]}×${preview.source[1]}`
      + `${preview.angle ? `, turned ${preview.angle}°` : ""}`
      + `, placed at ${preview.fitted[0]}×${preview.fitted[1]} on the panel.`
    : "");
}

async function renderPreview() {
  if (!state?.image) {
    showPreview(null);
    return;
  }
  setText(ui.editorInfo, "Rendering…");
  try {
    const result = await postJSON("/api/preview");
    if (!result.ok) {
      showPreview(null);
      lastPreviewKey = "";
      toast(result.error || "The image couldn't be rendered", "bad");
      return;
    }
    if (state) state.editor.preview = result;
    lastPreviewKey = result.key;
    showPreview(result);
  } catch (err) {
    showPreview(null);
    toast(`The image couldn't be rendered: ${err.message}`, "bad");
  }
}

async function setEditorOptions() {
  try {
    render(await postJSON("/api/editor", {
      fit: radioValue(ui.editorFit),
      dither: radioValue(ui.editorDither),
    }));
  } catch (err) {
    toast(`Couldn't change the render options: ${err.message}`, "bad");
    return;
  }
  await renderPreview();
}

function panelPoint(event) {
  const rect = ui.previewDevice.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: ((event.clientX - rect.left) / rect.width) * PANEL_W,
    y: ((event.clientY - rect.top) / rect.height) * PANEL_H,
  };
}

function drawLoupe(centre) {
  if (!currentPreview) return;
  const viewW = PANEL_W / ZOOM;
  const viewH = PANEL_H / ZOOM;
  const left = Math.min(PANEL_W - viewW, Math.max(0, centre.x - viewW / 2));
  const top = Math.min(PANEL_H - viewH, Math.max(0, centre.y - viewH / 2));
  loupeCentre = { x: left + viewW / 2, y: top + viewH / 2 };
  ui.previewZoom.style.backgroundImage = `url("${currentPreview.device}")`;
  ui.previewZoom.style.backgroundSize = `${PANEL_W * ZOOM}px ${PANEL_H * ZOOM}px`;
  ui.previewZoom.style.backgroundPosition = `${-left * ZOOM}px ${-top * ZOOM}px`;
  ui.previewSel.style.left = `${left}px`;
  ui.previewSel.style.top = `${top}px`;
  ui.previewSel.style.width = `${viewW}px`;
  ui.previewSel.style.height = `${viewH}px`;
}

// ── image picker ───────────────────────────────────────────────────────────
let pickerDir = "";
let pickerParent = null;

function joinPath(dir, name) {
  const separator = dir.includes("\\") && !dir.includes("/") ? "\\" : "/";
  return dir.endsWith(separator) ? dir + name : dir + separator + name;
}

function sizeText(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} kB`;
  return `${bytes} B`;
}

function pickerItem(name, size, folder, onClick) {
  const row = el("button", `picker-item${folder ? " folder" : ""}`);
  row.type = "button";
  row.append(el("span", null, name));
  if (size) row.append(el("span", "size", size));
  row.addEventListener("click", onClick);
  return row;
}

async function loadDir(dir) {
  let data;
  try {
    data = await getJSON(`/api/files?dir=${encodeURIComponent(dir || "")}`);
  } catch (err) {
    toast(`Couldn't open ${dir || "the image folder"}: ${err.message}`, "bad");
    return;
  }
  pickerDir = data.dir;
  pickerParent = data.parent;
  ui.pickerDir.textContent = data.dir;
  ui.pickerUp.disabled = !data.parent;
  ui.pickerList.replaceChildren();
  if (!data.dirs.length && !data.files.length) {
    ui.pickerList.append(el("p", "picker-none", "No images or folders here. Go up a folder to keep looking."));
  }
  for (const name of data.dirs) {
    ui.pickerList.append(pickerItem(name, "Folder", true, () => loadDir(joinPath(pickerDir, name))));
  }
  for (const file of data.files) {
    ui.pickerList.append(pickerItem(file.name, sizeText(file.size), false,
      () => chooseImage(joinPath(pickerDir, file.name))));
  }
  ui.pickerList.scrollTop = 0;
}

async function chooseImage(path) {
  try {
    render(await postJSON("/api/image", { path }));
    ui.picker.close();
    await renderPreview();          // never a push without a preview on screen
  } catch (err) {
    toast(`Couldn't use that image: ${err.message}`, "bad");
  }
}

// ── queue ──────────────────────────────────────────────────────────────────
function createJobRow(job) {
  const tr = el("tr");
  const stateCell = el("td");
  const wrap = el("span", "status-cell");
  const mark = el("span");
  const word = el("span", "state-word");
  wrap.append(mark, word);
  stateCell.append(wrap);
  const idCell = el("td");
  const link = el("button", "id-link");
  link.type = "button";
  link.append(pixelText(job.addr, 2));
  link.setAttribute("aria-label", `Open tag ${job.addr}`);
  link.addEventListener("click", () => openInspector(job.addr));
  idCell.append(link);
  const command = el("td");
  const detail = el("td", "detail");
  const age = el("td", "dim");
  tr.append(stateCell, idCell, command, detail, age);
  tr._parts = { mark, word, command, detail, age };
  return tr;
}

function updateJobRow(tr, job) {
  const parts = tr._parts;
  const finished = job.state === "done" || job.state === "cancelled";
  setClass(tr, job.state === "failed" ? "failed" : finished ? "finished" : "");
  setClass(parts.mark, `mark ${JOB_MARK[job.state] || "s-silent"}`);
  setText(parts.word, JOB_STATE[job.state] || job.state);
  const kind = JOB_LABEL[job.kind] || job.kind;
  const named = job.kind === "image" || job.kind === "firmware";
  setText(parts.command, named ? `${kind}: ${job.label}` : kind);
  setText(parts.age, `${ageText(job.age)} ago`);

  const fraction = job.state === "running" ? progressFraction(state?.progress) : null;
  const signature = fraction === null ? `t${job.error || ""}` : `p${state.progress}`;
  if (parts.detail.dataset.sig !== signature) {
    parts.detail.dataset.sig = signature;
    parts.detail.replaceChildren();
    if (fraction !== null) {
      const bar = el("div", "progress");
      const track = el("div", "progress-track");
      const fill = el("i");
      fill.style.width = `${Math.round(fraction * 100)}%`;
      track.append(fill);
      bar.append(track, el("span", null, state.progress));
      parts.detail.append(bar);
    } else {
      parts.detail.textContent = job.error || "";
    }
  }
}

function renderQueue() {
  const jobs = state?.queue || [];
  const rank = { running: 0, pending: 1, failed: 2, done: 3, cancelled: 3 };
  // live work on top; finished work below it, newest first
  const ordered = [...jobs].sort((a, b) => {
    const diff = (rank[a.state] ?? 3) - (rank[b.state] ?? 3);
    if (diff) return diff;
    return rank[a.state] <= 1 ? a.id - b.id : b.id - a.id;
  });
  ui.queueWrap.hidden = jobs.length === 0;
  ui.queueEmpty.hidden = jobs.length > 0;
  ui.queueCancel.disabled = !state?.sending && !jobs.some((job) => job.state === "pending");
  syncKeyed(ui.queueRows, ordered, (job) => job.id, createJobRow, updateJobRow);
}

// ── logs ───────────────────────────────────────────────────────────────────
function eventTime(at) {
  const date = new Date(at * 1000);
  const time = date.toTimeString().slice(0, 8);
  return date.toDateString() === new Date().toDateString()
    ? time
    : `${date.toLocaleDateString(undefined, { month: "short", day: "numeric" })} ${time}`;
}

function syncSelect(select, firstLabel, values, labelOf) {
  const signature = values.join(",");
  if (select.dataset.sig === signature) return;
  select.dataset.sig = signature;
  const keep = select.value;
  const first = el("option", null, firstLabel);
  first.value = "";
  select.replaceChildren(first);
  for (const value of values) {
    const option = el("option", null, labelOf ? labelOf(value) : value);
    option.value = value;
    select.append(option);
  }
  if (values.includes(keep)) select.value = keep;
}

function renderLogs() {
  const info = tagRows();
  syncSelect(ui.logsTag, "All tags", info.map((row) => row.hex),
    (hex) => {
      const alias = info.find((row) => row.hex === hex)?.alias;
      return alias ? `${hex} (${alias})` : hex;
    });
  syncSelect(ui.logsEvent, "All events", [...new Set(events.map((row) => row.event))].sort());

  const tagFilter = ui.logsTag.value;
  const eventFilter = ui.logsEvent.value;
  // Every poll is a sync event, so they would bury everything else. Picking "sync"
  // in the menu shows them too.
  const hideSync = !ui.logsSync.checked && eventFilter !== "sync";
  const aliases = info.map((row) => row.alias).join("|");
  const signature = JSON.stringify(
    [events.length, events.at(-1), tagFilter, eventFilter, hideSync, aliases]);
  if (signatures.logs === signature) return;
  signatures.logs = signature;

  const rows = events.filter(
    (row) => (!tagFilter || row.hex === tagFilter)
      && (!eventFilter || row.event === eventFilter)
      && !(hideSync && row.event === "sync"),
  );
  ui.logsWrap.hidden = rows.length === 0;
  ui.logsEmpty.hidden = rows.length > 0;
  ui.logsRows.replaceChildren();
  for (const row of [...rows].reverse().slice(0, 500)) {
    const tr = el("tr", /fail|error/.test(row.event) ? "bad-event" : null);
    const idCell = el("td");
    if (row.hex) {
      const link = el("button", "id-link");
      link.type = "button";
      link.append(pixelText(row.hex, 1.5));
      link.setAttribute("aria-label", `Open tag ${row.hex}`);
      link.addEventListener("click", () => openInspector(row.hex));
      idCell.append(link);
    }
    tr.append(
      el("td", "dim", eventTime(row.at)),
      idCell,
      el("td", "dim", info.find((tag) => tag.hex === row.hex)?.alias || ""),
      el("td", "event", row.event),
      el("td", "detail", row.detail),
      el("td", "dim", row.count > 1 ? `×${row.count}` : ""),
    );
    ui.logsRows.append(tr);
  }
}

/** One durable event row: [id, unix time, hex id, kind, detail].
 *
 *  Ids come from the database and only ever grow, so an id we have already shown
 *  is a duplicate (a retried poll, say) and is dropped. Consecutive identical
 *  rows collapse into xN, which is how the firmware collapses its own log.
 */
function addEvent(id, at, hexId, kind, detail) {
  if (id <= newestEventId) return;
  newestEventId = id;
  const hex = hexId || "";
  const previous = events[events.length - 1];
  if (previous && (detail || "") === previous.detail && previous.hex === hex && previous.event === kind) {
    previous.count += 1;
    previous.at = at;
    previous.id = id;
    return;
  }
  events.push({ id, at, hex, event: kind, detail: detail || "", count: 1 });
  if (events.length > 2000) events.shift();
}

// ── hub: serial panes ──────────────────────────────────────────────────────
function buildPane(pane) {
  const root = el("section", "pane");
  root.innerHTML = `
    <div class="pane-head">
      <h2 class="pane-name"></h2>
      <span class="pane-status"><span class="mark"></span><span class="pane-status-text"></span></span>
    </div>
    <div class="pane-controls">
      <input class="port" type="text" list="port-options" spellcheck="false" autocomplete="off"
             placeholder="COM4" aria-label="${pane.name} port">
      <input class="baud" type="number" min="300" step="1" aria-label="${pane.name} baud rate">
      <button class="toggle-open primary" type="button">Open</button>
      <button class="toggle-dtr" type="button" title="DTR drives the BOOT pin and holds where you put it">DTR</button>
      <button class="reset" type="button" title="Pulses the reset line (RTS) for 100 ms">Reset</button>
      <button class="clear quiet" type="button">Clear log</button>
    </div>
    <div class="log" tabindex="0" role="log" aria-label="${pane.name} serial log"></div>
    <form class="pane-send">
      <input class="send-text" type="text" spellcheck="false" autocomplete="off"
             placeholder="Send to the port, e.g. P" aria-label="${pane.name} text to send">
      <label class="send-hex"><input class="send-hex-box" type="checkbox"> Hex</label>
      <select class="send-eol" aria-label="Line ending">
        <option value="lf">LF</option><option value="crlf">CR+LF</option>
        <option value="cr">CR</option><option value="none">none</option>
      </select>
      <button class="send-btn" type="submit">Send</button>
    </form>`;

  const view = {
    root,
    name: root.querySelector(".pane-name"),
    status: root.querySelector(".pane-status"),
    statusMark: root.querySelector(".pane-status .mark"),
    statusText: root.querySelector(".pane-status-text"),
    port: root.querySelector(".port"),
    baud: root.querySelector(".baud"),
    openBtn: root.querySelector(".toggle-open"),
    dtrBtn: root.querySelector(".toggle-dtr"),
    resetBtn: root.querySelector(".reset"),
    clearBtn: root.querySelector(".clear"),
    log: root.querySelector(".log"),
    sendForm: root.querySelector(".pane-send"),
    sendText: root.querySelector(".send-text"),
    sendHex: root.querySelector(".send-hex-box"),
    sendEol: root.querySelector(".send-eol"),
    sendBtn: root.querySelector(".send-btn"),
  };

  // Debug: send what was typed (text or hex bytes) over this pane's port. Up/Down recall history.
  const sent = [];
  let recall = 0;
  view.sendForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const text = view.sendText.value;
    if (!text && view.sendEol.value === "none") return;
    try {
      render(await postJSON(`/api/pane/${pane.key}/send`, {
        text, hex: view.sendHex.checked, eol: view.sendEol.value,
      }));
      if (text && sent[sent.length - 1] !== text) sent.push(text);
      recall = sent.length;
      view.sendText.value = "";
    } catch (err) {
      toast(`Not sent: ${err.message}`, "bad");
    }
  });
  view.sendText.addEventListener("keydown", (event) => {
    if (event.key !== "ArrowUp" && event.key !== "ArrowDown") return;
    event.preventDefault();
    recall = Math.max(0, Math.min(sent.length, recall + (event.key === "ArrowUp" ? -1 : 1)));
    view.sendText.value = sent[recall] || "";
  });

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
    toast(`That didn't reach the port: ${err.message}`, "bad");
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
  while (excess-- > 0) view.log.firstChild.remove();
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
  if (view) view.log.replaceChildren();
}

/** Add a batch of lines to a pane.
 *
 *  Sequence numbers are monotonic per pane, so a line already shown can never be
 *  shown again, whatever the server sends. That is deliberate: a cursor-format
 *  mistake once made the server replay its whole buffer on every poll and the
 *  console looked like it was re-printing itself. A server restart (sequence
 *  numbers starting over) is handled in tick() by the server's own cursor going
 *  backwards, which clears the pane first.
 */
function ingest(key, lines) {
  const view = panes.get(key);
  let last = lastSeq.get(key) || 0;
  for (const [seq, stamp, text] of lines) {
    if (seq <= last) continue;
    last = seq;
    rememberLine(key, stamp, text);
    if (view) appendRow(view, stamp, text);
  }
  lastSeq.set(key, last);
}

function renderPanes() {
  const active = document.activeElement;
  for (const pane of state?.panes || []) {
    const view = panes.get(pane.key) || buildPane(pane);
    const isHub = pane.key === state.hub;
    view.root.hidden = !isHub && prefs.show_tag_port === false;
    setText(view.name, isHub ? `Hub port (${pane.name})` : `Second port (${pane.name})`);
    if (active !== view.port) view.port.value = pane.port || "";
    if (active !== view.baud) view.baud.value = pane.baud;
    setText(view.openBtn, pane.open ? "Close" : "Open");
    view.openBtn.classList.toggle("primary", !pane.open);
    view.dtrBtn.classList.toggle("on", !!pane.dtr);
    view.dtrBtn.setAttribute("aria-pressed", String(!!pane.dtr));
    view.resetBtn.disabled = !pane.open;
    view.sendBtn.disabled = !pane.open;
    const error = pane.status.startsWith("error");
    setText(view.statusText, pane.status);
    setClass(view.status, `pane-status${error ? " error" : ""}`);
    setClass(view.statusMark, `mark ${error ? "s-alert" : pane.open ? "s-online" : "s-silent"}`);
  }
}

// ── hub: firmware and panel ────────────────────────────────────────────────
function renderHub() {
  renderPanes();
  const caps = state?.hub_caps || {};
  const pane = hubPane();
  setText(ui.hubBanner, caps.banner || (pane?.open
    ? "Waiting for the hub's start-up banner."
    : "Open the hub port to talk to your tags."));

  const word = (value) => (value === true ? "Yes" : value === false ? "No" : "Unknown");
  const facts = [
    ["Read tag flash", word(caps.dump)],
    ["Fast image batches", word(caps.batch)],
    ["Draw on its own panel", word(caps.show)],
  ];
  const signature = JSON.stringify(facts);
  if (signatures.caps !== signature) {
    signatures.caps = signature;
    ui.hubCaps.replaceChildren();
    for (const [key, value] of facts) ui.hubCaps.append(el("dt", null, key), el("dd", null, value));
  }

  const display = state?.hub_display || {};
  const active = document.activeElement;
  if (active !== ui.displayEnabled) ui.displayEnabled.checked = !!display.enabled;
  if (active !== ui.displayAlias) ui.displayAlias.checked = !!display.show_alias;
  if (active !== ui.displayTitle) ui.displayTitle.value = display.title ?? "";
  if (active !== ui.displayTimeout) ui.displayTimeout.value = display.timeout_s ?? "";
  if (active !== ui.displayInterval) ui.displayInterval.value = display.min_interval_s ?? "";
  const blind = caps.show === false;
  ui.displayWarning.hidden = !blind;
  setText(ui.displayWarning, blind
    ? "This hub's firmware can't draw on its panel. Flash vusion-hub-latest.hex to use this."
    : "");
  ui.displayRefresh.disabled = !display.enabled || blind;
  setText(ui.displayResult, display.last_result ? `Last redraw: ${display.last_result}` : "");

  const shown = display.shown || [];
  const shownSig = shown.join(",");
  if (signatures.shown !== shownSig) {
    signatures.shown = shownSig;
    ui.displayShown.replaceChildren();
    if (shown.length) {
      ui.displayShown.append(el("span", "hint", "On the panel now:"));
      for (const hex of shown) ui.displayShown.append(pixelText(hex, 2));
    }
  }
}

async function saveDisplay(extra) {
  try {
    await postJSON("/api/hub-display", {
      enabled: ui.displayEnabled.checked,
      show_alias: ui.displayAlias.checked,
      title: ui.displayTitle.value,
      timeout_s: ui.displayTimeout.value,
      min_interval_s: ui.displayInterval.value,
      ...extra,
    });
  } catch (err) {
    toast(`Couldn't change the hub's panel settings: ${err.message}`, "bad");
  }
}

// ── top bar ────────────────────────────────────────────────────────────────
function renderPorts(ports) {
  const signature = (ports || []).map(([device]) => device).join(",");
  if (ui.portOptions.dataset.signature === signature) return;
  ui.portOptions.dataset.signature = signature;
  ui.portOptions.replaceChildren();
  for (const [device, description] of ports || []) {
    const option = el("option");
    option.value = device;
    option.label = description ? `${device}: ${description}` : device;
    ui.portOptions.append(option);
  }
}

function renderChrome() {
  renderPorts(state.ports);
  setClass(ui.status, "status");
  setText(ui.status, state.status === "ready" ? "" : state.status);
  ui.status.title = state.status;

  const hub = hubPane();
  const open = !!hub?.open;
  setClass(ui.linkState, `link-state${open ? "" : " closed"}`);
  setClass(ui.linkMark, `mark ${open ? "s-online" : "s-alert"}`);
  setText(ui.linkText, open ? `Hub on ${hub.port}` : "Hub port closed");

  const waiting = (state.queue || []).filter(
    (job) => job.state === "pending" || job.state === "running").length;
  ui.navFlash.hidden = !state.flash?.active;
  ui.navQueue.hidden = !waiting;
  setText(ui.navQueue, String(waiting));

  const fraction = state.sending ? progressFraction(state.progress) : null;
  ui.transfer.hidden = !state.sending;
  ui.transferFill.style.width = `${Math.round((fraction ?? 0) * 100)}%`;
}

// ── flash ──────────────────────────────────────────────────────────────────
// The server runs the flash and keeps its steps and output; this screen only shows them.
// GET /api/flash carries the output and the .hex list, so it is fetched when the screen
// opens and whenever the state says the output has grown.
let flashData = null;              // last GET /api/flash
let flashFetchedFor = "";          // "log_n|result" of that fetch
let flashFetching = false;
let flashMethod = "debugger";
const KIND_TEXT = {
  full: "bootloader and application",
  app: "application only",
  bootloader: "bootloader only",
  hub: "hub application",
};
const METHOD_TEXT = {
  debugger: "Uses the AXSDB debugger on USB. Works on a blank or broken chip.",
  serial: "Uses the chip's built-in bootloader over a serial adapter, with no debugger.",
};

async function refreshFlash() {
  if (flashFetching) return;
  flashFetching = true;
  try {
    flashData = await getJSON("/api/flash");
    flashFetchedFor = `${flashData.flash.log_n}|${flashData.flash.result}`;
  } catch (err) {
    /* the next poll tries again */
  } finally {
    flashFetching = false;
  }
  draw();
}

function flashKind(file) {
  return flashData?.files.find((item) => item.path === file)?.kind || "app";
}

function preferredFile(method) {
  const files = flashData?.files || [];
  const wanted = method === "debugger"
    ? (f) => f.kind === "full"
    : (f) => f.kind === "app";
  return (files.find((f) => wanted(f) && /latest/.test(f.name)) || files.find(wanted) || files[0])?.path;
}

function renderFlash() {
  const flash = state?.flash;
  if (!flash) return;
  const signature = `${flash.log_n}|${flash.result}`;
  if (!flashData || (signature !== flashFetchedFor && !flashFetching)) refreshFlash();

  // the form
  const method = flashMethod;
  setRadio(ui.flashMethod, method);
  setText(ui.flashMethodHint, METHOD_TEXT[method]);
  ui.flashPaneField.hidden = method !== "serial";

  const files = flashData?.files || [];
  const filesSig = files.map((file) => file.path).join("|");
  if (signatures.flashFiles !== filesSig) {
    signatures.flashFiles = filesSig;
    ui.flashFile.replaceChildren();
    if (!files.length) {
      const none = el("option", null, "No .hex files in Release/");
      none.value = "";
      ui.flashFile.append(none);
    }
    for (const file of files) {
      const option = el("option", null,
        `${file.name} (${Math.round(file.size / 1024)} kB, ${KIND_TEXT[file.kind]})`);
      option.value = file.path;
      ui.flashFile.append(option);
    }
    ui.flashFile.value = preferredFile(method) || "";
  }

  const panes = state.panes || [];
  const panesSig = panes.map((pane) => `${pane.key}|${pane.name}|${pane.port}`).join(",");
  if (signatures.flashPanes !== panesSig) {
    signatures.flashPanes = panesSig;
    const keep = ui.flashPane.value;
    ui.flashPane.replaceChildren();
    for (const pane of panes) {
      const option = el("option", null, `${pane.name}: ${pane.port || "no port set"}`);
      option.value = pane.key;
      ui.flashPane.append(option);
    }
    const other = panes.find((pane) => pane.key !== state.hub) || panes[0];
    ui.flashPane.value = keep && panes.some((pane) => pane.key === keep) ? keep : other?.key || "";
  }

  const file = ui.flashFile.value;
  const kind = flashKind(file);
  const partial = method === "debugger" && !!file && kind !== "full";
  ui.flashPartialField.hidden = !partial;
  if (!partial) ui.flashPartial.checked = false;

  const paneInfo = panes.find((pane) => pane.key === ui.flashPane.value);
  let warning = "";
  let blocked = false;
  if (method === "debugger") {
    if (!flash.axsdb.found) {
      warning = "AXSDB wasn't found. Set its location in Settings.";
      blocked = true;
    } else if (partial) {
      warning = `${KIND_TEXT[kind][0].toUpperCase()}${KIND_TEXT[kind].slice(1)} only. The debugger erases the whole chip first, so the bootloader is lost unless the file has it.`;
      blocked = !ui.flashPartial.checked;
    } else if (file) {
      warning = "The debugger erases the whole chip first.";
    }
  } else if (!paneInfo?.port) {
    warning = "Set a port for this pane on the Hub screen first.";
    blocked = true;
  } else {
    warning = `${paneInfo.port} is closed while flashing, then reopened. DTR must reach the chip's BOOT pin and RTS its reset.`;
    if (paneInfo.key === state.hub) warning += " This is the hub's own port, so the hub stops while it runs.";
  }
  setClass(ui.flashWarning, blocked ? "warning" : "hint");
  ui.flashWarning.replaceChildren(warning);
  if (!flash.axsdb.found && method === "debugger") {
    const link = el("a", null, "Open Settings");
    link.href = "#settings";
    ui.flashWarning.append(" ", link);
  }
  ui.flashStart.disabled = flash.active || blocked || !file;
  ui.flashCancel.hidden = !flash.active;
  for (const control of [ui.flashFile, ui.flashPane, ui.flashPartial]) control.disabled = flash.active;
  for (const input of ui.flashMethod.querySelectorAll("input")) input.disabled = flash.active;

  // the status
  const name = flash.file || "";
  let title = "Ready";
  let sub = "Nothing has been flashed since the server started.";
  if (flash.active) {
    title = `Flashing ${name}`;
    sub = `With the ${flash.method === "debugger" ? "USB debugger" : "serial bootloader"}. Don't unplug anything.`;
  } else if (flash.result === "ok") {
    title = `Flashed ${name}`;
    sub = `Took ${Math.round(flash.finished - flash.started)} s${flash.serial ? `. Chip serial ${flash.serial}` : ""}.`;
  } else if (flash.result === "cancelled") {
    title = "Stopped";
    sub = "The chip may be half-programmed. Flash again to recover it.";
  } else if (flash.result === "failed") {
    title = "Flashing failed";
    sub = `${name}, after ${Math.round(flash.finished - flash.started)} s.`;
  }
  setText(ui.flashResult, title);
  setText(ui.flashSub, sub);
  ui.flashError.hidden = flash.result !== "failed" || !flash.error;
  setText(ui.flashError, flash.error || "");

  const STEP_MARK = { waiting: "s-late", running: "s-waiting", done: "s-online", failed: "s-alert" };
  const STEP_WORD = { waiting: "Waiting", running: "In progress", done: "Done", failed: "Failed" };
  syncKeyed(ui.flashSteps, flash.steps, (step) => step.key, () => {
    const li = el("li");
    const mark = el("span");
    const label = el("span", "step-name");
    const detail = el("span", "step-detail");
    li.append(mark, label, detail);
    li._parts = { mark, label, detail, bar: null };
    return li;
  }, (li, step) => {
    const parts = li._parts;
    setClass(li, step.state);
    setClass(parts.mark, `mark ${STEP_MARK[step.state]}`);
    setText(parts.label, step.label);
    const fraction = step.state === "running" ? progressFraction(step.detail) : null;
    setText(parts.detail, fraction !== null ? "" : step.detail || STEP_WORD[step.state]);
    if (fraction !== null) {
      if (!parts.bar) {
        parts.bar = el("div", "progress");
        const track = el("div", "progress-track");
        track.append(el("i"));
        parts.bar.append(track, el("span"));
        li.append(parts.bar);
      }
      parts.bar.firstChild.firstChild.style.width = `${Math.round(fraction * 100)}%`;
      setText(parts.bar.lastChild, step.detail);
    } else if (parts.bar) {
      parts.bar.remove();
      parts.bar = null;
    }
  });

  const lines = flashData?.flash.log || [];
  const logSig = `${lines.length}|${lines.at(-1)}`;
  if (signatures.flashLog !== logSig) {
    signatures.flashLog = logSig;
    const stick = ui.flashLog.scrollHeight - ui.flashLog.scrollTop - ui.flashLog.clientHeight < 40;
    ui.flashLog.replaceChildren(...lines.map((line) => {
      const row = el("div", /fail|error|couldn't|didn't/i.test(line) ? "ln bad" : "ln");
      row.append(el("span", "m", line));
      return row;
    }));
    if (stick) ui.flashLog.scrollTop = ui.flashLog.scrollHeight;
  }
}

async function startFlash(event) {
  event.preventDefault();
  if (ui.flashStart.disabled) return;
  arm(ui.flashStart, "Press again to erase and flash", async () => {
    try {
      const response = await fetch("/api/flash", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          method: flashMethod,
          path: ui.flashFile.value,
          pane: ui.flashPane.value,
          allow_partial: ui.flashPartial.checked,
        }),
      });
      const result = await response.json();
      if (result.state) render(result.state);
      if (!result.ok) toast(result.error || "The flash didn't start", "bad");
      else refreshFlash();
    } catch (err) {
      toast(`Couldn't start the flash: ${err.message}`, "bad");
    }
  });
}

/** "5 minutes", "30 seconds", "1.5 hours" for a number of seconds. */
function minutesText(seconds) {
  if (seconds < 120) return `${seconds} seconds`;
  const minutes = seconds / 60;
  if (minutes < 120) return `${Number(minutes.toFixed(1))} minutes`;
  return `${Number((minutes / 60).toFixed(1))} hours`;
}

// ── settings ───────────────────────────────────────────────────────────────
// Stored by the server (shelfkit/prefs.py), so every browser sees the same values.
const DEFAULT_PREFS = {
  late_after_s: 330, silent_after_s: 630, forget_after_s: 900, low_battery_v: 2.5,
  fleet_view: "wall", wall_size: "full", show_tag_port: true,
};
const settingsInputs = {
  late_after_s: [ui.setLate, 60],
  silent_after_s: [ui.setSilent, 60],
  forget_after_s: [ui.setForget, 60],
  low_battery_v: [ui.setBattery, 1],
};
let settingsDirty = false;

function setSettingsDirty(dirty) {
  settingsDirty = dirty;
  ui.settingsSave.disabled = !dirty;
}

function loadSettingsForm() {
  for (const [name, [input, divisor]] of Object.entries(settingsInputs)) {
    input.value = String(Number((prefs[name] / divisor).toFixed(2)));
    input.classList.remove("invalid");
  }
  setRadio(ui.setView, prefs.fleet_view);
  setRadio(ui.setSize, prefs.wall_size);
  ui.setAxsdb.value = prefs.axsdb_path || "";
  ui.setHubPort.value = prefs.hub_port || "";
  ui.setTagPort.value = prefs.tag_port || "";
  ui.setShowTag.checked = prefs.show_tag_port !== false;
  setSettingsDirty(false);
}

/** Take the server's prefs when they differ from what this page last applied. */
function applyPrefs(next) {
  if (!next) return;
  const signature = JSON.stringify(next);
  if (signature === prefsSignature) return;
  prefsSignature = signature;
  prefs = next;
  fleetView = prefs.fleet_view;
  wallSize = prefs.wall_size;
  // blank tags letter their ID at a size that depends on the tag size
  for (const glass of ui.fleetWall.querySelectorAll(".glass")) delete glass.dataset.thumb;
  if (!settingsDirty) loadSettingsForm();
}

/** Save and return the server's answer, or null if it could not be reached. */
async function postPrefs(change) {
  try {
    const response = await fetch("/api/prefs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(change),
    });
    const result = await response.json();
    if (response.ok && result.ok) {
      prefsSignature = JSON.stringify(result.prefs);
      prefs = result.prefs;
      fleetView = prefs.fleet_view;
      wallSize = prefs.wall_size;
      render(result.state);
    }
    return { ok: response.ok && result.ok, error: result.error || response.statusText };
  } catch (err) {
    return { ok: false, error: `Couldn't reach the server: ${err.message}` };
  }
}

/** A toolbar choice (layout, tag size) is a setting too: it is saved as you pick it. */
async function savePref(change) {
  const result = await postPrefs(change);
  if (!result.ok) toast(`Couldn't save that setting. ${result.error}`, "bad");
}

function settingsFromForm() {
  const out = {};
  for (const [name, [input, divisor]] of Object.entries(settingsInputs)) {
    out[name] = input.value.trim() === "" ? null : Number(input.value) * divisor;
    if (Number.isNaN(out[name])) out[name] = null;
  }
  out.fleet_view = radioValue(ui.setView);
  out.wall_size = radioValue(ui.setSize);
  out.axsdb_path = ui.setAxsdb.value.trim();
  out.hub_port = ui.setHubPort.value.trim();
  out.tag_port = ui.setTagPort.value.trim();
  out.show_tag_port = ui.setShowTag.checked;
  return out;
}

async function submitSettings(event) {
  event.preventDefault();
  const values = settingsFromForm();
  let blank = false;
  for (const [name, [input]] of Object.entries(settingsInputs)) {
    input.classList.toggle("invalid", values[name] === null);
    blank = blank || values[name] === null;
  }
  if (blank) {
    setText(ui.settingsNote, "Fill in every number before saving.");
    return;
  }
  const result = await postPrefs(values);
  if (!result.ok) {
    setText(ui.settingsNote, `Not saved. ${result.error}.`);
    return;
  }
  loadSettingsForm();
  setText(ui.settingsNote, "Saved.");
}

async function restoreDefaults() {
  const result = await postPrefs(DEFAULT_PREFS);
  if (result.ok) {
    loadSettingsForm();
    setText(ui.settingsNote, "Defaults restored.");
  } else {
    setText(ui.settingsNote, `Not restored. ${result.error}.`);
  }
}

async function importAliases(file) {
  if (!file) return;
  let text;
  try {
    text = await file.text();
  } catch (err) {
    setText(ui.aliasesResult, `Couldn't read that file: ${err.message}`);
    return;
  }
  try {
    const payload = await postJSON("/api/aliases", { csv: text });
    const result = payload.result || {};
    render(payload.state);
    const list = result.problems || [];
    const problems = `${list.slice(0, 4).join(" ")}${list.length > 4 ? " More lines were skipped." : ""}`;
    setText(ui.aliasesResult, result.imported
      ? `Imported ${plural(result.imported, "tag")}. ${problems}`.trim()
      : `Nothing imported. ${problems || "The file had no tag rows."}`);
  } catch (err) {
    setText(ui.aliasesResult, `Couldn't import: ${err.message}`);
  }
}

function renderSettings() {
  // the form shows what the server holds until you start typing
  if (!settingsDirty) loadSettingsForm();
  const axsdb = state?.flash?.axsdb;
  if (axsdb) {
    setText(ui.setAxsdbState, axsdb.found
      ? `Found: ${axsdb.exe}${axsdb.detected ? " (the default install)" : ""}`
      : axsdb.path ? "Not found at the saved location." : "Not found in the default install or on PATH.");
    setClass(ui.setAxsdbState, axsdb.found ? "hint" : "warning");
  }
}

function render(next) {
  state = next;
  if (!state) return;
  applyPrefs(state.prefs);
  renderChrome();
  draw();
}

function draw() {
  if (!state) return;
  if (screen === "fleet") renderFleet();
  else if (screen === "editor") renderEditor();
  else if (screen === "queue") renderQueue();
  else if (screen === "logs") renderLogs();
  else if (screen === "hub") renderHub();
  else if (screen === "settings") renderSettings();
  else if (screen === "flash") renderFlash();
  renderInspector();
}

// ── polling ────────────────────────────────────────────────────────────────
function schedule() {
  clearTimeout(timer);
  timer = setTimeout(tick, POLL_MS);
}

// cursors as "key=epoch:seq": the server splits on "=" first (see parse_cursors)
function cursorQuery() {
  const parts = [];
  for (const [key, value] of cursorState) parts.push(`${key}=${value}`);
  return parts.join(",");
}

async function tick() {
  if (busy) {
    schedule();
    return;
  }
  busy = true;
  try {
    const data = await getJSON(`/api/poll?c=${encodeURIComponent(cursorQuery())}&e=${eventCursor}`);
    for (const [key, part] of Object.entries(data.panes || {})) {
      const previousSeq = Number((cursorState.get(key) || "0:0").split(":")[1]) || 0;
      // Cleared in the page, or the server restarted and its sequence numbers
      // started over: either way what we are showing is stale.
      if (part.reset || part.cursor < previousSeq) clearLog(key);
      if (!replayed.has(key) && part.lines.length) {
        // First attach: the server hands back its retained buffer. Say so, or a
        // reload looks like the log repeating itself.
        replayed.add(key);
        rememberLine(key, "", `# attached, replaying ${part.lines.length} retained lines`);
        const view = panes.get(key);
        if (view) appendRow(view, "", `# attached, replaying ${part.lines.length} retained lines`);
      }
      ingest(key, part.lines);
      cursorState.set(key, `${part.epoch}:${part.cursor}`);
    }
    for (const row of data.events || []) addEvent(row[0], row[1], row[2], row[3], row[4]);
    if (typeof data.event_cursor === "number") eventCursor = data.event_cursor;
    render(data.state);
  } catch (err) {
    setClass(ui.status, "status bad");
    setText(ui.status, "Can't reach the server. Retrying. Is shelfkit-server.py still running?");
  } finally {
    busy = false;
    schedule();
  }
}

async function copyLogs() {
  let text;
  try {
    const response = await fetch("/api/log", { cache: "no-store" });
    text = await response.text();
  } catch (err) {
    toast(`Couldn't read the log: ${err.message}`, "bad");
    return;
  }
  const lines = text.split("\n").length - 1;
  if (!lines) {
    toast("The log is empty, so nothing was copied");
    return;
  }
  try {
    await navigator.clipboard.writeText(text);
    toast(`Copied ${plural(lines, "line")}`);
    return;
  } catch (err) {
    /* no clipboard API on plain http from another host: fall through */
  }
  const area = document.createElement("textarea");
  area.value = text;
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.append(area);
  area.select();
  const ok = document.execCommand("copy");
  area.remove();
  if (ok) toast(`Copied ${plural(lines, "line")}`);
  else toast("The browser blocked the copy. Use Save log instead.", "bad");
}

// ── wiring ─────────────────────────────────────────────────────────────────
ui.fleetSearch.addEventListener("input", () => {
  fleetSearch = ui.fleetSearch.value;
  draw();
});

ui.fleetFilters.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-filter]");
  if (!button) return;
  fleetFilter = button.dataset.filter;
  draw();
});

ui.fleetView.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-view]");
  if (!button) return;
  fleetView = button.dataset.view;
  savePref({ fleet_view: fleetView });
  draw();
});

ui.wallSize.addEventListener("click", (event) => {
  const button = event.target.closest("button[data-size]");
  if (!button) return;
  wallSize = button.dataset.size;
  savePref({ wall_size: wallSize });
  // blank tags letter their ID at a size that depends on this
  for (const glass of ui.fleetWall.querySelectorAll(".glass")) delete glass.dataset.thumb;
  draw();
});

ui.fleetTable.querySelector("thead").addEventListener("click", (event) => {
  const th = event.target.closest("th[data-sort]");
  if (!th) return;
  const key = th.dataset.sort;
  fleetSort = { key, dir: fleetSort.key === key ? -fleetSort.dir : 1 };
  draw();
});

ui.fleetAll.addEventListener("change", () => {
  const rows = visibleRows();
  for (const row of rows) {
    if (ui.fleetAll.checked) picked.add(row.hex);
    else picked.delete(row.hex);
  }
  draw();
});

ui.fleetOpenHub.addEventListener("click", () => {
  const hub = hubPane();
  if (hub?.port) command(hub.key, "open", { port: hub.port, baud: hub.baud });
  else location.hash = "#hub";
});

ui.fleetForgetStale.addEventListener("click", () => {
  arm(ui.fleetForgetStale, "Press again to forget them", () => {
    forget("/api/tags/forget", { not_seen_for: prefs.forget_after_s });
  });
});

ui.bulkPush.addEventListener("click", () => openEditorFor([...picked]));
ui.bulkClear.addEventListener("click", () => {
  picked.clear();
  draw();
});
ui.bulkService.addEventListener("click", async () => {
  const hexes = [...picked];
  let queued = 0;
  for (const hex of hexes) {
    try {
      const payload = await postJSON(`/api/tags/${hex}/service`, {});
      if (payload.result?.ok) queued += 1;
      else toast(`${hex}: ${payload.result?.error || "not queued"}`, "bad");
      render(payload.state);
    } catch (err) {
      toast(`${hex}: ${err.message}`, "bad");
    }
  }
  if (queued) toast(`Queued service labels for ${plural(queued, "tag")}`);
});
ui.bulkForget.addEventListener("click", () => {
  arm(ui.bulkForget, `Press again to forget ${plural(picked.size, "tag")}`, async () => {
    const addrs = [...picked];
    if (addrs.length && await forget("/api/tags/forget", { addrs })) {
      picked.clear();
      draw();
    }
  });
});

ui.editorBrowse.addEventListener("click", () => {
  ui.picker.showModal();
  loadDir("");
});
ui.editorRender.addEventListener("click", renderPreview);
ui.editorPush.addEventListener("click", pushImage);
ui.targetsOnline.addEventListener("click", () => {
  targets.clear();
  for (const row of tagRows()) {
    if (!row.quiet) targets.add(row.hex);
  }
  draw();
});
ui.targetsNone.addEventListener("click", () => {
  targets.clear();
  draw();
});

ui.previewGlass.addEventListener("pointermove", (event) => {
  const point = panelPoint(event);
  if (point) drawLoupe(point);
});
ui.previewGlass.addEventListener("pointerdown", (event) => {
  const point = panelPoint(event);
  if (point) drawLoupe(point);
});
ui.previewGlass.addEventListener("keydown", (event) => {
  const step = { ArrowLeft: [-8, 0], ArrowRight: [8, 0], ArrowUp: [0, -8], ArrowDown: [0, 8] }[event.key];
  if (!step) return;
  event.preventDefault();
  drawLoupe({ x: loupeCentre.x + step[0], y: loupeCentre.y + step[1] });
});

ui.queueCancel.addEventListener("click", async () => {
  try {
    const payload = await postJSON("/api/queue/cancel", {});
    render(payload.state);
    const count = payload.result?.cancelled || 0;
    toast(count ? `Cancelled ${plural(count, "command")}` : "Stopping the running command");
  } catch (err) {
    toast(`Couldn't cancel: ${err.message}`, "bad");
  }
});

ui.logsTag.addEventListener("change", draw);
ui.logsEvent.addEventListener("change", draw);
ui.logsSync.addEventListener("change", draw);
ui.copyLogs.addEventListener("click", copyLogs);

for (const input of [ui.displayEnabled, ui.displayAlias, ui.displayTitle, ui.displayTimeout, ui.displayInterval]) {
  input.addEventListener("change", () => saveDisplay());
}
ui.displayRefresh.addEventListener("click", async () => {
  await saveDisplay({ refresh: true });
  toast("The hub's panel redraws next");
});

ui.settingsForm.addEventListener("submit", submitSettings);
ui.settingsForm.addEventListener("input", () => {
  setSettingsDirty(true);
  setText(ui.settingsNote, "");
});
ui.settingsReset.addEventListener("click", restoreDefaults);
ui.aliasesImport.addEventListener("click", () => ui.aliasesFile.click());
ui.aliasesFile.addEventListener("change", async () => {
  await importAliases(ui.aliasesFile.files[0]);
  ui.aliasesFile.value = "";
});

ui.flashForm.addEventListener("submit", startFlash);
ui.flashMethod.addEventListener("change", () => {
  flashMethod = radioValue(ui.flashMethod) || "debugger";
  ui.flashFile.value = preferredFile(flashMethod) || ui.flashFile.value;
  disarm();
  draw();
});
for (const control of [ui.flashFile, ui.flashPane, ui.flashPartial]) {
  control.addEventListener("change", () => {
    disarm();
    draw();
  });
}
ui.flashCancel.addEventListener("click", async () => {
  try {
    const result = await postJSON("/api/flash/cancel", {});
    if (result.state) render(result.state);
    toast(result.ok ? "Stopping the flash. The chip may be left half-programmed." : result.error, result.ok ? null : "bad");
  } catch (err) {
    toast(`Couldn't stop the flash: ${err.message}`, "bad");
  }
});

ui.inspectorClose.addEventListener("click", closeInspector);
ui.inspectorForm.addEventListener("submit", saveInspector);
ui.inspectorForm.addEventListener("input", () => setFormDirty(true));
ui.inspectorPush.addEventListener("click", () => {
  if (inspected) openEditorFor([inspected]);
});
ui.inspectorService.addEventListener("click", () => {
  if (inspected) {
    queueCommand(inspected, "service", {}, `Service label queued for ${inspected}`, ui.inspectorService);
  }
});
ui.inspectorAssign.addEventListener("click", async () => {
  if (!inspected) return;
  const ok = await queueCommand(inspected, "assign", { id: ui.inspectorNewId.value.trim() },
    `ID change queued for ${inspected}`, ui.inspectorAssign);
  if (ok) ui.inspectorNewId.value = "";
});
ui.inspectorFlash.addEventListener("click", () => {
  if (inspected && ui.inspectorFw.value) {
    queueCommand(inspected, "flash", { path: ui.inspectorFw.value },
      `Firmware queued for ${inspected}`, ui.inspectorFlash);
  }
});
ui.inspectorRead.addEventListener("click", () => {
  if (inspected) {
    // 0x3000 = update header + identity record + reserved sector: all metadata
    queueCommand(inspected, "read", { start: 0, length: 0x3000 },
      `Flash read queued for ${inspected}`, ui.inspectorRead);
  }
});
ui.inspectorForget.addEventListener("click", () => {
  arm(ui.inspectorForget, "Press again to forget", () => {
    if (inspected) forget(`/api/tags/${inspected}/forget`, {});
  });
});
ui.inspectorWipe.addEventListener("click", () => {
  arm(ui.inspectorWipe, "Press again to erase", () => {
    if (inspected) {
      queueCommand(inspected, "wipe", {}, `Factory reset queued for ${inspected}`, ui.inspectorWipe);
    }
  });
});

ui.pickerUp.addEventListener("click", () => {
  if (pickerParent) loadDir(pickerParent);
});
ui.pickerCancel.addEventListener("click", () => ui.picker.close());
ui.picker.addEventListener("click", (event) => {
  if (event.target === ui.picker) ui.picker.close();   // a click on the backdrop
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !ui.picker.open && inspected) closeInspector();
});

async function boot() {
  applyTheme(currentTheme(), false);   // label the button for the theme already applied
  $("brand").append(pixelText("SHELFKIT", 2));
  // the bar's height changes when it wraps, and the inspector docks right below it
  const bar = document.querySelector(".topbar");
  new ResizeObserver(() => {
    document.documentElement.style.setProperty("--topbar-h", `${bar.offsetHeight}px`);
  }).observe(bar);
  while (!state) {
    try {
      state = await getJSON("/api/state");
    } catch (err) {
      setClass(ui.status, "status bad");
      setText(ui.status, "Can't reach the server. Is shelfkit-server.py running?");
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
  }
  for (const pane of state.panes) cursorState.set(pane.key, `${pane.epoch}:0`);
  renderChrome();
  show(location.hash.slice(1) || "fleet");
  schedule();
}

boot();


// ── battery voltage history (inspector) ───────────────────────────────────────
const vhist = { tag: null, seq: 0 };
const vui = {
  range: $("vhist-range"), custom: $("vhist-custom"), from: $("vhist-from"),
  to: $("vhist-to"), chart: $("vhist-chart"), stats: $("vhist-stats"),
};

function vhistWindow() {
  const now = Date.now() / 1000;
  if (vui.range.value === "custom") {
    const since = vui.from.value ? new Date(vui.from.value).getTime() / 1000 : now - 7 * 86400;
    const until = vui.to.value ? new Date(vui.to.value).getTime() / 1000 : now;
    return [since, until];
  }
  const days = Number(vui.range.value);
  return [days ? now - days * 86400 : 0, now];
}

function svgEl(name, attrs, text) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", name);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  if (text != null) node.textContent = text;
  return node;
}

function fmtTime(sec, spanSec) {
  const d = new Date(sec * 1000);
  if (spanSec <= 2 * 86400) {
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

function drawVoltage(data) {
  const svg = vui.chart;
  svg.replaceChildren();
  const W = 360, H = 170, L = 34, R = 8, T = 8, B = 22;
  const pts = data.points || [];
  if (!pts.length) {
    svg.append(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle" },
      "No readings in this period"));
    return;
  }
  const t0 = pts[0][0];
  const t1 = Math.max(pts[pts.length - 1][0], t0 + 1);
  let lo = Math.min(...pts.map((p) => p[1]));
  let hi = Math.max(...pts.map((p) => p[1]));
  const low = prefs.low_battery_v;
  lo = Math.min(lo, low) - 0.02;
  hi = Math.max(hi, lo + 0.1) + 0.02;
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);

  for (let i = 0; i <= 4; i++) {
    const v = lo + ((hi - lo) * i) / 4;
    svg.append(svgEl("line", { class: "grid-line", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    svg.append(svgEl("text", { x: L - 4, y: y(v) + 3, "text-anchor": "end" }, v.toFixed(2)));
  }
  for (let i = 0; i <= 3; i++) {
    const t = t0 + ((t1 - t0) * i) / 3;
    const anchor = i === 0 ? "start" : i === 3 ? "end" : "middle";
    svg.append(svgEl("text", { x: x(t), y: H - 7, "text-anchor": anchor }, fmtTime(t, t1 - t0)));
  }
  svg.append(svgEl("line", { class: "low-line", x1: L, x2: W - R, y1: y(low), y2: y(low) }));
  svg.append(svgEl("polyline", { class: "series",
    points: pts.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ") }));
  if (pts.length <= 150) {
    for (const p of pts) svg.append(svgEl("circle", { class: "dots", cx: x(p[0]), cy: y(p[1]), r: 1.4 }));
  }
}

function drawVoltageStats(data) {
  const s = data.stats;
  vui.stats.replaceChildren();
  if (!s) return;
  const span = s.span_h >= 48 ? `${(s.span_h / 24).toFixed(1)} days` : `${s.span_h.toFixed(1)} h`;
  const sign = s.drain_net_mv >= 0 ? "−" : "+";
  const rows = [
    ["Readings", `${data.count} over ${span}`],
    ["From → to", `${s.first_v.toFixed(3)} V → ${s.last_v.toFixed(3)} V`],
    ["Min / max", `${s.min_v.toFixed(3)} / ${s.max_v.toFixed(3)} V`],
    ["Average drain", s.drain_mv_per_day == null ? "Needs two readings further apart"
      : `${s.drain_mv_per_day.toFixed(1)} mV per day (trend line)`],
    ["Net change", `${sign}${Math.abs(s.drain_net_mv).toFixed(0)} mV`],
    ["Current (rough)", s.drain_ua_estimate == null
      ? "Needs 1 h of readings and a falling voltage"
      : `about ${s.drain_ua_estimate} µA, from the CR2450 curve`],
  ];
  for (const [k, v] of rows) vui.stats.append(el("dt", null, k), el("dd", null, v));
}

async function refreshVoltage() {
  if (!inspected) return;
  const mine = ++vhist.seq;           // only the newest request may draw
  try {
    const [since, until] = vhistWindow();
    const response = await fetch(`/api/voltage?tag=${inspected}&since=${since}&until=${until}`);
    const data = await response.json();
    if (mine !== vhist.seq || data.error || data.hex_id !== inspected) return;
    drawVoltage(data);
    drawVoltageStats(data);
  } catch (error) {
    /* the next refresh tries again */
  }
}

vui.range.addEventListener("change", () => {
  vui.custom.hidden = vui.range.value !== "custom";
  refreshVoltage();
});
vui.from.addEventListener("change", refreshVoltage);
vui.to.addEventListener("change", refreshVoltage);
setInterval(() => {
  if (inspected && !ui.inspector.hidden) {
    vhist.tag = inspected;
    refreshVoltage();
  }
}, 30000);
