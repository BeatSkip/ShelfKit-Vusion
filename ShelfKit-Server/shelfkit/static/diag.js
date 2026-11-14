"use strict";

/* The Diagnostics screen: one tag at a time, with room to look closely.
 *
 * A large battery plot (drag across it to measure a stretch: drain, current, charge and
 * power come from that selection), the tag's own event log beside it, and the tag picker
 * from the inspector to move between tags. Loaded after app.js and uses its helpers.
 *
 * Panels below the plot sit in an auto-filling grid (.diag-panels): a new diagnostic is
 * one more <section class="diag-panel"> there.
 */

const DIAG_CELL_MAH = 620;            // CR2450, the same figure the server's estimate uses
const DIAG_LOG_LIMIT = 3000;
const DIAG_PLOT_MIN = 200, DIAG_PLOT_MAX = 1400;
const DIAG_LOG_MIN = 280, DIAG_LOG_MAX = 1000;

const diag = {
  tag: null,              // hex of the tag on the screen
  seq: 0,                 // only the newest plot request may draw
  selSeq: 0,              // the same for the selection's figures
  since: 0,               // where the tag's current measurement starts
  runs: [],               // its archived measurements, drawn as markers
  data: null,             // last /api/voltage answer for the plot
  sel: null,              // [from, to] in unix seconds, or null
  selStats: null,         // /api/voltage answer for the selection
  zoom: null,             // [from, to] the plot is zoomed to, or null
  plot: null,             // the scales of the last drawing
  drag: null,             // a selection being dragged: {t, x}
  events: [],             // this tag's log, oldest first, identical neighbours folded
  newest: 0,              // highest event id in it
  loading: false,         // the log is being fetched; live rows wait in `waiting`
  waiting: [],
  logSig: "",
  factsSig: "",
};

const dui = {
  body: $("diag-body"), empty: $("diag-empty"),
  id: $("diag-id"), alias: $("diag-alias"),
  pick: $("diag-pick"), prev: $("diag-prev"), next: $("diag-next"),
  inspect: $("diag-inspect"),
  range: $("diag-range"), zoom: $("diag-zoom"), unzoom: $("diag-unzoom"), clear: $("diag-clear"),
  plot: $("diag-plot"), chart: $("diag-chart"), grip: $("diag-plot-grip"),
  readout: $("diag-readout"),
  statsTitle: $("diag-stats-title"), stats: $("diag-stats"), statsNote: $("diag-stats-note"),
  facts: $("diag-facts"),
  split: $("diag-split"),
  logEvent: $("diag-event"), logSync: $("diag-sync"), logRows: $("diag-rows"),
  logWrap: $("diag-log-wrap"), logEmpty: $("diag-log-empty"), logCount: $("diag-log-count"),
};

// ── which tag ────────────────────────────────────────────────────────────────
function setDiagTag(hex) {
  const wanted = String(hex).toUpperCase().padStart(4, "0");
  if (diag.tag === wanted) return;
  diag.tag = wanted;
  store("diag.tag", wanted);
  diag.sel = null;
  diag.selStats = null;
  diag.zoom = null;
  diag.data = null;
  diag.runs = [];
  diag.since = 0;
  diag.factsSig = "";
  drawDiagPlot();
  renderDiagStats();
  loadDiagLog();
  refreshDiag();
  if (screen === "diagnostics") draw();
}

function stepDiagTag(delta) {
  const flat = tagsByShelf().flatMap((group) => group.rows);
  const next = flat[flat.findIndex((row) => row.hex === diag.tag) + delta];
  if (next) setDiagTag(next.hex);
}

/** Open the Diagnostics screen on one tag (the inspector's button, a log row). */
function openDiagnostics(hex) {
  setDiagTag(hex);
  if (screen !== "diagnostics") location.hash = "#diagnostics";
}

// ── the battery plot ─────────────────────────────────────────────────────────
function diagWindow() {
  const now = Date.now() / 1000;
  if (diag.zoom) return diag.zoom;
  if (dui.range.value === "run") return [diag.since || 0, now];
  const days = Number(dui.range.value);
  return [days ? now - days * 86400 : 0, now];
}

/** A step from the 1-2-5 series that gives about `count` ticks over `span`. */
function niceStep(span, count) {
  const raw = span / Math.max(1, count);
  const power = 10 ** Math.floor(Math.log10(raw));
  const unit = raw / power;
  return (unit <= 1 ? 1 : unit <= 2 ? 2 : unit <= 5 ? 5 : 10) * power;
}

/** An axis label: the day alone is enough only when the ticks are a day or more apart. */
function diagTimeLabel(sec, spanSec, stepSec) {
  const d = new Date(sec * 1000);
  const time = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (spanSec <= 86400) return time;
  const day = d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
  return stepSec < 86400 ? `${day} ${time}` : day;
}

function spanText(seconds) {
  if (seconds < 90) return `${Math.round(seconds)} s`;
  if (seconds < 2 * 3600) return `${Math.round(seconds / 60)} min`;
  if (seconds < 48 * 3600) return `${(seconds / 3600).toFixed(1)} h`;
  return `${(seconds / 86400).toFixed(1)} days`;
}

function drawDiagPlot() {
  const svg = dui.chart;
  const W = Math.max(240, Math.floor(dui.plot.clientWidth));
  const H = Math.max(120, Math.floor(dui.plot.clientHeight));
  svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
  svg.replaceChildren();
  diag.plot = null;
  const pts = diag.data?.points || [];
  if (!pts.length) {
    svg.append(svgEl("text", { x: W / 2, y: H / 2, "text-anchor": "middle", class: "none" },
      !diag.tag ? "" : diag.data ? "No battery readings in this period" : "Loading the readings"));
    setText(dui.readout, "");
    return;
  }
  const L = 50, R = 14, T = 12, B = 28;
  const t0 = pts[0][0];
  const t1 = Math.max(pts[pts.length - 1][0], t0 + 1);
  let lo = Infinity, hi = -Infinity;
  for (const p of pts) {
    if (p[1] < lo) lo = p[1];
    if (p[1] > hi) hi = p[1];
  }
  // The voltage of a coin cell moves by millivolts: the axis hugs the readings, and the
  // low-battery line is drawn only when it is in view.
  const pad = Math.max((hi - lo) * 0.08, 0.004);
  lo -= pad;
  hi += pad;
  const x = (t) => L + ((t - t0) / (t1 - t0)) * (W - L - R);
  const y = (v) => T + (1 - (v - lo) / (hi - lo)) * (H - T - B);
  const tAt = (px) => t0 + ((Math.min(W - R, Math.max(L, px)) - L) / (W - L - R)) * (t1 - t0);
  diag.plot = { x, y, tAt, t0, t1, L, R, T, B, W, H, pts };

  const vStep = niceStep(hi - lo, Math.max(2, Math.floor((H - T - B) / 44)));
  const digits = vStep < 0.01 ? 3 : 2;
  for (let v = Math.ceil(lo / vStep) * vStep; v <= hi + 1e-9; v += vStep) {
    svg.append(svgEl("line", { class: "grid-line", x1: L, x2: W - R, y1: y(v), y2: y(v) }));
    svg.append(svgEl("text", { x: L - 6, y: y(v) + 4, "text-anchor": "end" }, v.toFixed(digits)));
  }
  const ticks = Math.max(2, Math.floor((W - L - R) / 150));
  for (let i = 0; i <= ticks; i++) {
    const t = t0 + ((t1 - t0) * i) / ticks;
    const anchor = i === 0 ? "start" : i === ticks ? "end" : "middle";
    svg.append(svgEl("line", { class: "grid-line tick", x1: x(t), x2: x(t), y1: T, y2: H - B }));
    svg.append(svgEl("text", { x: x(t), y: H - 9, "text-anchor": anchor }, diagTimeLabel(t, t1 - t0, (t1 - t0) / ticks)));
  }
  svg.append(svgEl("text", { x: 4, y: T + 2, class: "unit" }, "V"));

  const low = prefs.low_battery_v;
  if (low > lo && low < hi) {
    svg.append(svgEl("line", { class: "low-line", x1: L, x2: W - R, y1: y(low), y2: y(low) }));
    svg.append(svgEl("text", { x: W - R - 4, y: y(low) - 4, "text-anchor": "end", class: "low-text" },
      "Low battery"));
  }
  // where an archived measurement ended: a new battery or a new firmware
  for (const run of diag.runs) {
    if (run.ended_at <= t0 || run.ended_at >= t1) continue;
    const at = x(run.ended_at);
    svg.append(svgEl("line", { class: "run-line", x1: at, x2: at, y1: T, y2: H - B }));
    svg.append(svgEl("text", { x: at + 4, y: T + 10, class: "run-text" },
      POWER_REASON_TEXT[run.reason] || run.reason));
  }

  diag.plot.selRect = svgEl("rect", { class: "sel", y: T, height: H - T - B, visibility: "hidden" });
  diag.plot.selA = svgEl("line", { class: "sel-edge", y1: T, y2: H - B, visibility: "hidden" });
  diag.plot.selB = svgEl("line", { class: "sel-edge", y1: T, y2: H - B, visibility: "hidden" });
  svg.append(diag.plot.selRect);
  svg.append(svgEl("polyline", { class: "series",
    points: pts.map((p) => `${x(p[0]).toFixed(1)},${y(p[1]).toFixed(1)}`).join(" ") }));
  if (pts.length <= 400) {
    for (const p of pts) svg.append(svgEl("circle", { class: "dots", cx: x(p[0]), cy: y(p[1]), r: 1.8 }));
  }
  diag.plot.hoverLine = svgEl("line", { class: "hover-line", y1: T, y2: H - B, visibility: "hidden" });
  diag.plot.hoverDot = svgEl("circle", { class: "hover-dot", r: 4, visibility: "hidden" });
  svg.append(diag.plot.selA, diag.plot.selB, diag.plot.hoverLine, diag.plot.hoverDot);
  drawDiagSelection();
}

function drawDiagSelection() {
  const plot = diag.plot;
  const has = Boolean(diag.sel);
  dui.zoom.disabled = !has;
  dui.clear.disabled = !has;
  dui.unzoom.hidden = !diag.zoom;
  dui.range.disabled = Boolean(diag.zoom);
  if (!plot) return;
  const from = has ? Math.max(diag.sel[0], plot.t0) : 0;
  const to = has ? Math.min(diag.sel[1], plot.t1) : 0;
  const shown = has && to > from;
  for (const node of [plot.selRect, plot.selA, plot.selB]) {
    node.setAttribute("visibility", shown ? "visible" : "hidden");
  }
  if (!shown) return;
  const a = plot.x(from), b = plot.x(to);
  plot.selRect.setAttribute("x", a);
  plot.selRect.setAttribute("width", Math.max(1, b - a));
  plot.selA.setAttribute("x1", a);
  plot.selA.setAttribute("x2", a);
  plot.selB.setAttribute("x1", b);
  plot.selB.setAttribute("x2", b);
}

function diagPointerX(event) {
  const box = dui.chart.getBoundingClientRect();
  return ((event.clientX - box.left) / box.width) * (diag.plot ? diag.plot.W : box.width);
}

function diagHover(event) {
  const plot = diag.plot;
  if (!plot) return;
  const t = plot.tAt(diagPointerX(event));
  // the reading nearest in time (the points are in time order)
  let lowIdx = 0, highIdx = plot.pts.length - 1;
  while (highIdx - lowIdx > 1) {
    const mid = (lowIdx + highIdx) >> 1;
    if (plot.pts[mid][0] < t) lowIdx = mid;
    else highIdx = mid;
  }
  const p = Math.abs(plot.pts[lowIdx][0] - t) <= Math.abs(plot.pts[highIdx][0] - t)
    ? plot.pts[lowIdx] : plot.pts[highIdx];
  const px = plot.x(p[0]);
  plot.hoverLine.setAttribute("x1", px);
  plot.hoverLine.setAttribute("x2", px);
  plot.hoverDot.setAttribute("cx", px);
  plot.hoverDot.setAttribute("cy", plot.y(p[1]));
  plot.hoverLine.setAttribute("visibility", "visible");
  plot.hoverDot.setAttribute("visibility", "visible");
  setText(dui.readout, `${fmtWhen(p[0])}   ${p[1].toFixed(3)} V`);
}

function diagHoverOff() {
  if (!diag.plot) return;
  diag.plot.hoverLine.setAttribute("visibility", "hidden");
  diag.plot.hoverDot.setAttribute("visibility", "hidden");
  setText(dui.readout, "");
}

dui.chart.addEventListener("pointerdown", (event) => {
  if (!diag.plot || event.button !== 0) return;
  const px = diagPointerX(event);
  diag.drag = { t: diag.plot.tAt(px), x: event.clientX, moved: false };
  dui.chart.setPointerCapture(event.pointerId);
  event.preventDefault();
});
dui.chart.addEventListener("pointermove", (event) => {
  diagHover(event);
  if (!diag.drag || !diag.plot) return;
  if (Math.abs(event.clientX - diag.drag.x) < 4 && !diag.drag.moved) return;
  diag.drag.moved = true;
  const t = diag.plot.tAt(diagPointerX(event));
  diag.sel = [Math.min(diag.drag.t, t), Math.max(diag.drag.t, t)];
  diag.selStats = null;
  drawDiagSelection();
  renderDiagStats();
});
function diagDragEnd(event) {
  if (!diag.drag) return;
  const moved = diag.drag.moved;
  diag.drag = null;
  if (dui.chart.hasPointerCapture(event.pointerId)) dui.chart.releasePointerCapture(event.pointerId);
  if (!moved) {                       // a plain click drops the selection
    clearDiagSelection();
    return;
  }
  refreshDiagSelection();
}
dui.chart.addEventListener("pointerup", diagDragEnd);
dui.chart.addEventListener("pointercancel", diagDragEnd);
dui.chart.addEventListener("pointerleave", diagHoverOff);

function clearDiagSelection() {
  diag.sel = null;
  diag.selStats = null;
  diag.selSeq += 1;
  drawDiagSelection();
  renderDiagStats();
}

// ── the figures under the plot ───────────────────────────────────────────────
/** Rows for one /api/voltage answer: what the server measured plus what follows from it. */
function diagStatRows(data) {
  const s = data.stats;
  const rows = [
    ["Period", `${fmtWhen(s.first_at)} → ${fmtWhen(s.last_at)}`],
    ["Length", spanText(s.span_h * 3600)],
    ["Readings", String(data.count)],
    ["Voltage", `${s.first_v.toFixed(3)} V → ${s.last_v.toFixed(3)} V`],
    ["Min / max", `${s.min_v.toFixed(3)} / ${s.max_v.toFixed(3)} V`],
    ["Net change", `${s.drain_net_mv >= 0 ? "−" : "+"}${Math.abs(s.drain_net_mv).toFixed(0)} mV`],
    ["Drain", s.drain_mv_per_day == null ? "Needs two readings further apart"
      : `${s.drain_mv_per_day.toFixed(1)} mV per day (trend line)`],
  ];
  const ua = s.drain_ua_trend ?? s.drain_ua_estimate;
  if (ua == null) {
    rows.push(["Current", "Needs at least 1 h of readings"]);
    return rows;
  }
  if (!(ua > 0)) {
    rows.push(["Current", s.min_v >= 3.0
      ? "Not measurable above 3.0 V, where the cell's curve is flat"
      : "No measurable drain: the voltage did not fall"]);
    return rows;
  }
  const mah = (ua * s.span_h) / 1000;
  rows.push(
    ["Current", `about ${ua < 10 ? ua.toFixed(1) : Math.round(ua)} µA average`],
    ["Charge used", `${mah < 10 ? mah.toFixed(2) : mah.toFixed(1)} mAh `
      + `(${((mah / DIAG_CELL_MAH) * 100).toFixed(1)} % of a CR2450)`],
    ["Power", `about ${(ua * s.mean_v).toFixed(0)} µW at ${s.mean_v.toFixed(2)} V`],
    ["Energy used", `${(mah * s.mean_v).toFixed(2)} mWh`],
    ["A full cell lasts", `about ${spanText((DIAG_CELL_MAH * 1000 / ua) * 3600)} at this rate`],
  );
  return rows;
}

function renderDiagStats() {
  let title, rows = [], note = "";
  if (diag.sel) {
    title = `Selection: ${fmtWhen(diag.sel[0])} → ${fmtWhen(diag.sel[1])} `
      + `(${spanText(diag.sel[1] - diag.sel[0])})`;
    if (diag.drag) note = "Release to measure this stretch.";
    else if (!diag.selStats) note = "Measuring this stretch.";
    else if (!diag.selStats.stats) note = "No battery readings in this stretch.";
    else rows = diagStatRows(diag.selStats);
  } else {
    title = diag.zoom ? "Zoomed period" : "Whole period";
    if (diag.data?.stats) rows = diagStatRows(diag.data);
    else if (diag.data) note = "No battery readings in this period.";
  }
  if (rows.length) {
    note = "Current, charge and power are read off the CR2450 discharge curve. A coin cell's "
      + "voltage is nearly flat for most of its life, so treat them as rough; longer "
      + "stretches are more trustworthy.";
  }
  setText(dui.statsTitle, title);
  dui.stats.replaceChildren();
  for (const [key, value] of rows) dui.stats.append(el("dt", null, key), el("dd", null, value));
  dui.statsNote.hidden = !note;
  setText(dui.statsNote, note);
}

async function refreshDiagSelection() {
  if (!diag.sel || !diag.tag) return;
  const mine = ++diag.selSeq;
  const [from, to] = diag.sel;
  renderDiagStats();
  try {
    const data = await getJSON(`/api/voltage?tag=${diag.tag}&since=${from}&until=${to}`);
    if (mine !== diag.selSeq || data.hex_id !== diag.tag) return;
    diag.selStats = data;
  } catch (error) {
    if (mine !== diag.selSeq) return;
    diag.selStats = { count: 0, stats: null };
  }
  renderDiagStats();
}

async function refreshDiag() {
  if (!diag.tag) return;
  const mine = ++diag.seq;
  const tag = diag.tag;
  try {
    const runs = await getJSON(`/api/power-runs?tag=${tag}`);
    if (mine !== diag.seq || runs.hex_id !== tag) return;
    diag.runs = runs.runs || [];
    diag.since = runs.current_since || 0;
    const [since, until] = diagWindow();
    const data = await getJSON(`/api/voltage?tag=${tag}&since=${since}&until=${until}`);
    if (mine !== diag.seq || data.hex_id !== tag) return;
    diag.data = data;
    if (!diag.drag) {
      drawDiagPlot();
      renderDiagStats();
    }
  } catch (error) {
    /* the next refresh tries again */
  }
}

dui.range.value = stored("diag.range", "run");
if (!dui.range.value) dui.range.value = "run";
dui.range.addEventListener("change", () => {
  store("diag.range", dui.range.value);
  refreshDiag();
});
dui.zoom.addEventListener("click", () => {
  if (!diag.sel) return;
  diag.zoom = diag.sel;
  diag.sel = null;
  diag.selStats = null;
  diag.selSeq += 1;
  drawDiagSelection();
  refreshDiag();
});
dui.unzoom.addEventListener("click", () => {
  diag.zoom = null;
  drawDiagSelection();
  refreshDiag();
});
dui.clear.addEventListener("click", clearDiagSelection);

// ── resizing: the plot's height and the log's width ──────────────────────────
function setPlotHeight(px, keep) {
  const height = Math.round(Math.min(DIAG_PLOT_MAX, Math.max(DIAG_PLOT_MIN, px)));
  dui.plot.style.height = `${height}px`;
  dui.grip.setAttribute("aria-valuenow", height);
  if (keep) store("diag.plot.h", String(height));
}

function setLogWidth(px, keep) {
  const width = Math.round(Math.min(DIAG_LOG_MAX, Math.max(DIAG_LOG_MIN, px)));
  dui.body.style.setProperty("--diag-log-w", `${width}px`);
  dui.split.setAttribute("aria-valuenow", width);
  if (keep) store("diag.log.w", String(width));
}

/** Drag a separator: `apply(start value, pointer delta in px, final)`. */
function dragHandle(handle, read, apply, axis, keyStep) {
  handle.addEventListener("pointerdown", (event) => {
    if (event.button !== 0) return;
    const start = read();
    const origin = axis === "y" ? event.clientY : event.clientX;
    handle.setPointerCapture(event.pointerId);
    handle.classList.add("dragging");
    const delta = (ev) => (axis === "y" ? ev.clientY : ev.clientX) - origin;
    const move = (ev) => apply(start, delta(ev), false);
    const done = (ev) => {
      apply(start, delta(ev), true);
      handle.classList.remove("dragging");
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", done);
      handle.removeEventListener("pointercancel", done);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", done);
    handle.addEventListener("pointercancel", done);
    event.preventDefault();
  });
  handle.addEventListener("keydown", (event) => {
    const step = keyStep[event.key];
    if (!step) return;
    event.preventDefault();
    apply(read(), step, true);
  });
}

dragHandle(dui.grip, () => dui.plot.offsetHeight,
  (start, delta, keep) => setPlotHeight(start + delta, keep), "y",
  { ArrowDown: 24, ArrowUp: -24 });
// the log is on the right, so dragging its edge left makes it wider
dragHandle(dui.split, () => dui.logWrap.closest(".diag-log").offsetWidth,
  (start, delta, keep) => setLogWidth(start - delta, keep), "x",
  { ArrowLeft: 24, ArrowRight: -24 });
dui.grip.addEventListener("dblclick", () => setPlotHeight(400, true));
dui.split.addEventListener("dblclick", () => setLogWidth(440, true));
setPlotHeight(Number(stored("diag.plot.h", "400")) || 400, false);
setLogWidth(Number(stored("diag.log.w", "440")) || 440, false);

// The plot is drawn in screen pixels, so its lettering stays the same size at any shape:
// redraw whenever the box changes (the grip, the window, the inspector opening).
new ResizeObserver(() => {
  if (screen === "diagnostics") drawDiagPlot();
}).observe(dui.plot);

// ── the tag's log ────────────────────────────────────────────────────────────
function addDiagEvent(id, at, kind, detail) {
  if (id <= diag.newest) return;
  diag.newest = id;
  const previous = diag.events[diag.events.length - 1];
  if (previous && previous.event === kind && previous.detail === (detail || "")) {
    previous.count += 1;
    previous.at = at;
    return;
  }
  diag.events.push({ at, event: kind, detail: detail || "", count: 1 });
  if (diag.events.length > DIAG_LOG_LIMIT) diag.events.shift();
}

/** Called by app.js for every event the poll delivers. */
function diagEvent(id, at, hex, kind, detail) {
  if (!diag.tag || hex !== diag.tag) return;
  if (diag.loading) diag.waiting.push([id, at, kind, detail]);
  else addDiagEvent(id, at, kind, detail);
}

async function loadDiagLog() {
  const tag = diag.tag;
  diag.events = [];
  diag.newest = 0;
  diag.waiting = [];
  diag.loading = true;
  diag.logSig = "";
  try {
    const data = await getJSON(`/api/events?tag=${tag}&limit=${DIAG_LOG_LIMIT}`);
    if (tag !== diag.tag) return;         // another tag was picked meanwhile
    for (const row of data.events || []) addDiagEvent(row[0], row[1], row[3], row[4]);
  } catch (error) {
    /* live events still arrive below */
  }
  if (tag !== diag.tag) return;
  for (const row of diag.waiting) addDiagEvent(...row);
  diag.waiting = [];
  diag.loading = false;
  renderDiagLog();
}

function renderDiagLog() {
  syncSelect(dui.logEvent, "All events", [...new Set(diag.events.map((row) => row.event))].sort());
  const filter = dui.logEvent.value;
  const hideSync = !dui.logSync.checked && filter !== "sync";
  const last = diag.events[diag.events.length - 1];
  const signature = JSON.stringify([diag.tag, diag.events.length, last, filter, hideSync, diag.loading]);
  if (diag.logSig === signature) return;
  diag.logSig = signature;
  const rows = diag.events.filter(
    (row) => (!filter || row.event === filter) && !(hideSync && row.event === "sync"));
  dui.logWrap.hidden = rows.length === 0;
  dui.logEmpty.hidden = rows.length > 0;
  setText(dui.logEmpty, diag.loading ? "Loading the log."
    : diag.events.length ? "No event matches this filter."
      : "The server has recorded nothing for this tag yet.");
  setText(dui.logCount, rows.length ? plural(rows.length, "row") : "");
  // keep the reader's place: only follow new rows while the list is at its top
  const atTop = dui.logWrap.scrollTop < 8;
  dui.logRows.replaceChildren();
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    const tr = el("tr", /fail|error/.test(row.event) ? "bad-event" : null);
    tr.append(
      el("td", "dim time", eventTime(row.at)),
      el("td", "event", row.event),
      el("td", "detail", row.detail),
      el("td", "dim", row.count > 1 ? `×${row.count}` : ""),
    );
    dui.logRows.append(tr);
  }
  if (atTop) dui.logWrap.scrollTop = 0;
}

dui.logSync.checked = stored("diag.sync", "1") === "1";
dui.logSync.addEventListener("change", () => {
  store("diag.sync", dui.logSync.checked ? "1" : "0");
  renderDiagLog();
});
dui.logEvent.addEventListener("change", renderDiagLog);

// ── the screen ───────────────────────────────────────────────────────────────
function renderDiagFacts(row) {
  const reported = row.fw ? `${row.fw.version}-${row.fw.build}` : null;
  const place = row.row == null ? "Not on a shelf"
    : `${shelfName(String(row.row))}${row.col != null ? `, slot ${row.col}` : ""}`;
  const facts = [
    ["Status", statusWord(row)],
    ["Heard", heardText(row)],
    ["Check-ins", String(row.count)],
    ["Ping interval", row.pollPending != null
      ? `${minutesText(row.pollS)}, changing to ${minutesText(row.pollPending)}`
      : `${minutesText(row.pollS)}${row.pollSet ? "" : " (firmware default)"}`],
    ["Battery", row.battery != null ? `${row.battery.toFixed(2)} V, ${row.batteryPct ?? 0}%` : "No reading", row.low],
    ["Firmware", reported || "Not reported"],
    ["Firmware's estimate", row.fw
      ? `avg ${row.fw.avg_ua} µA, about ${row.fw.life_days} days on a CR2450` : "Not reported"],
    ["Reported", row.fw ? `${ageText(row.fw.age)} ago` : "Never"],
    ["Last push", row.push ? `${ageText(row.push.age)} ago, ${row.push.name}` : "None"],
    ["Place", place],
    ["Notes", row.notes || "None"],
  ];
  const signature = JSON.stringify(facts);
  if (diag.factsSig === signature) return;
  diag.factsSig = signature;
  dui.facts.replaceChildren();
  for (const [key, value, bad] of facts) {
    dui.facts.append(el("dt", null, key), el("dd", bad ? "bad" : null, value));
  }
}

function renderDiag() {
  const rows = tagRows();
  dui.empty.hidden = rows.length > 0;
  dui.body.hidden = rows.length === 0;
  dui.pick.closest(".tag-pick").hidden = rows.length === 0;
  dui.inspect.hidden = rows.length === 0;
  if (!rows.length) return;
  let row = rows.find((candidate) => candidate.hex === diag.tag);
  if (!row) {                         // first visit, or the tag was forgotten
    const remembered = stored("diag.tag", "");
    row = rows.find((candidate) => candidate.hex === (inspected || remembered)) || rows[0];
    setDiagTag(row.hex);
    return;                           // setDiagTag draws again
  }
  if (!dui.id.firstChild) dui.id.append(pixelText(row.hex, 4));
  setPixelText(dui.id.firstChild, row.hex, 4);
  setClass(dui.alias, row.alias ? "inspector-alias" : "inspector-alias none");
  setText(dui.alias, row.alias || "No alias");
  renderTagPicker({ pick: dui.pick, prev: dui.prev, next: dui.next }, diag.tag);
  renderDiagFacts(row);
  renderDiagLog();
}

/** The screen came into view: its plot had no size while it was hidden. */
function diagShown() {
  drawDiagPlot();
  refreshDiag();
}

dui.pick.addEventListener("change", () => setDiagTag(dui.pick.value));
dui.prev.addEventListener("click", () => stepDiagTag(-1));
dui.next.addEventListener("click", () => stepDiagTag(1));
dui.inspect.addEventListener("click", () => {
  if (diag.tag) openInspector(diag.tag);
});
$("inspector-diag").addEventListener("click", () => {
  if (!inspected) return;
  const hex = inspected;
  closeInspector();                   // the page needs the width the panel takes
  openDiagnostics(hex);
});

setInterval(() => {
  if (screen === "diagnostics" && !diag.drag) refreshDiag();
}, 30000);

if (screen === "diagnostics") {
  draw();
  diagShown();
}
