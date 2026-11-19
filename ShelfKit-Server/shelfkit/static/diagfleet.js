"use strict";

/* Diagnostics › Fleet: every tag side by side.
 *
 * Figures from /api/diag/fleet (shelfkit/diagstats.py): each tag's drain and current over
 * the period, its check-ins (missed ones counted from gaps between polls, hours in which
 * the server heard no tag at all left out), its pushes, and the firmware versions compared
 * stretch by stretch. Status, battery and names come from the live state (tagRows()).
 * Loaded after diag.js; the mode switch and the shared helpers live there.
 */

const dfl = {
  data: null,             // the last /api/diag/fleet answer
  key: "",                // the request it answered
  seq: 0,
  loadedAt: 0,
  sort: stored("dfl.sort", "battery"),
  dir: Number(stored("dfl.dir", "1")) || 1,
  filter: stored("dfl.filter", "all"),
  sig: "",
};

const fui = {
  root: $("diag-fleet"), period: $("dfl-period"), shelf: $("dfl-shelf"), updated: $("dfl-updated"),
  kpis: $("dfl-kpis"), att: $("dfl-att"), attCount: $("dfl-att-count"), attNone: $("dfl-att-none"),
  batt: $("dfl-batt"), battNote: $("dfl-batt-note"), drain: $("dfl-drain"), drainNote: $("dfl-drain-note"),
  fwMix: $("dfl-fw-mix"), fw: $("dfl-fw"), heat: $("dfl-heat"), heatNote: $("dfl-heat-note"),
  filter: $("dfl-filter"), head: $("dfl-head"), rows: $("dfl-rows"),
};

const DFL_COLUMNS = [
  ["hex", "Tag"], ["name", "Name"], ["shelf", "Shelf"], ["status", "Status"],
  ["battery", "Battery"], ["drain", "Drain"], ["current", "Current"], ["life", "A cell lasts"],
  ["fw", "Firmware"], ["heard", "Heard"], ["missed", "Check-ins missed"], ["pushes", "Pushes failed"],
];

// ── loading ──────────────────────────────────────────────────────────────────
function fleetShelfTags() {
  const shelf = fui.shelf.value;
  if (!shelf) return null;
  return tagRows().filter((row) => (row.row === null ? "none" : String(row.row)) === shelf)
    .map((row) => row.hex);
}

async function refreshFleetDiag(force) {
  const days = Number(fui.period.value) || 7;
  const tags = fleetShelfTags();
  const key = `${days}|${tags ? tags.join(",") : ""}`;
  if (!force && dfl.key === key && Date.now() - dfl.loadedAt < 20000) return;
  const mine = ++dfl.seq;
  const until = Date.now() / 1000;
  const query = `since=${until - days * 86400}&until=${until}` + (tags ? `&tags=${tags.join(",") || "FFFF"}` : "");
  try {
    const data = await getJSON(`/api/diag/fleet?${query}`);
    if (mine !== dfl.seq) return;
    dfl.data = data;
    dfl.key = key;
    dfl.loadedAt = Date.now();
    dfl.sig = "";
    renderFleetDiag();
  } catch (error) {
    if (mine === dfl.seq) setText(fui.updated, "Could not load the fleet figures; trying again.");
  }
}

/** The Diagnostics screen came into view in Fleet mode, or the mode switched to it. */
function fleetShown() {
  renderFleetDiag();
  refreshFleetDiag(false);
}

// ── one tag's figures, live state and fleet answer together ────────────────────
function fleetRows() {
  const figures = new Map((dfl.data?.tags || []).map((tag) => [tag.hex_id, tag]));
  const only = fleetShelfTags();
  return tagRows().filter((row) => !only || only.includes(row.hex)).map((live) => {
    const f = figures.get(live.hex) || null;
    // the server restarted and has not heard the tag since: its last stored reading
    const row = live.battery == null && f?.last_v != null
      ? { ...live, battery: f.last_v, low: f.last_v < prefs.low_battery_v } : live;
    const drain = f?.drain?.enough ? f.drain : null;
    return {
      row, f, drain,
      mv: drain ? drain.drain_mv_per_day : null,
      ua: drain ? drain.ua : null,
      checkins: f?.checkins || null,
      day: f?.day || null,
      pushes: f?.pushes || null,
      fw: row.fw ? `${row.fw.version}-${row.fw.build}` : f?.fw || null,
    };
  });
}

function fleetReasons(item, medianMv) {
  const { row } = item;
  const out = [];
  if (row.status === "silent") out.push([`Silent: last heard ${row.seen == null ? "never" : `${ageText(row.seen)} ago`}`, true]);
  else if (row.status === "late") out.push([`Late: last heard ${ageText(row.seen)} ago`, false]);
  if (row.low) out.push([`Battery low: ${row.battery.toFixed(2)} V`, true]);
  if (item.mv != null && medianMv > 0 && item.mv > Math.max(medianMv * 2, medianMv + 3)) {
    out.push([`Drains ${(item.mv / medianMv).toFixed(1)}× the fleet median`, false]);
  }
  const day = item.day;
  if (day && day.missed >= 3 && day.expected && day.missed / day.expected > 0.05 && row.status !== "silent") {
    out.push([`${plural(day.missed, "check-in")} missed in the last 24 h`, false]);
  }
  const failed = item.pushes?.failed || 0;
  if (failed) out.push([`${failed} ${failed === 1 ? "push" : "pushes"} failed`, true]);
  else if (row.failed) out.push([row.reason, true]);
  return out;
}

// ── drawing ──────────────────────────────────────────────────────────────────
/** "3.2 mV/day", or "rising 1.5" when the voltage went up (a cell recovering, warmth). */
function drainLabel(mv) {
  if (mv == null) return "—";
  return mv < 0 ? `rising ${Math.abs(mv).toFixed(1)}` : `${mv.toFixed(1)} mV/day`;
}

function uaLabel(ua, mv) {
  if (ua == null || (mv != null && mv <= 0) || !(ua > 0)) return "—";
  return `${ua < 10 ? ua.toFixed(1) : Math.round(ua)} µA`;
}

function kpi(label, value, sub, bad) {
  const box = el("div", bad ? "dfl-kpi bad" : "dfl-kpi");
  box.append(el("span", "k-label", label), el("span", "k-value", value), el("span", "k-sub", sub || ""));
  return box;
}

function tagButton(cls, item, open) {
  const button = el("button", cls);
  button.type = "button";
  button.title = `Open the diagnostics of ${item.row.hex}`;
  button.addEventListener("click", () => openDiagnostics(open || item.row.hex));
  return button;
}

function renderFleetKpis(items, data) {
  const rows = items.map((item) => item.row);
  const heard = rows.filter((row) => row.status !== "late" && row.status !== "silent").length;
  const late = rows.filter((row) => row.status === "late").length;
  const silent = rows.filter((row) => row.status === "silent").length;
  const withV = rows.filter((row) => row.battery != null).sort((a, b) => a.battery - b.battery);
  const lowest = withV[0];
  const t = data?.totals || {};
  const expected = t.expected || 0;
  const pushes = (t.push_delivered || 0) + (t.push_failed || 0);
  const ua = data?.median_ua;
  fui.kpis.replaceChildren(
    kpi("Tags checking in", `${heard} of ${rows.length}`,
      [late && `${late} late`, silent && `${silent} silent`].filter(Boolean).join(", ") || "all on time", silent > 0),
    kpi("Lowest battery", lowest ? `${lowest.battery.toFixed(2)} V` : "No reading",
      lowest ? `${lowest.hex}${lowest.alias ? ` ${lowest.alias}` : ""}` : "", Boolean(lowest?.low)),
    kpi("Median drain", data?.median_drain != null ? `${data.median_drain.toFixed(1)} mV` : "Not yet",
      data?.median_drain != null ? "per day, from the trend lines" : "needs 6 h of readings per tag"),
    kpi("Median current", ua != null ? `${ua < 10 ? ua.toFixed(1) : Math.round(ua)} µA` : "Not yet",
      ua > 0 ? `a CR2450 lasts about ${diagLifeText(ua)}` : "from the CR2450 curve"),
    kpi("Check-ins heard", expected ? `${(100 * (expected - t.missed) / expected).toFixed(1)} %` : "Not yet",
      expected ? `${t.missed.toLocaleString()} of ${expected.toLocaleString()} missed` : "", expected && t.missed / expected > 0.05),
    kpi("Pushes delivered", pushes ? `${(100 * t.push_delivered / pushes).toFixed(1)} %` : "None",
      pushes ? (t.push_failed ? `${t.push_failed} of ${pushes} failed` : `all ${pushes} delivered`) : "nothing pushed in this period",
      t.push_failed > 0),
  );
}

function renderFleetAttention(items, medianMv) {
  const list = items.map((item) => ({ item, reasons: fleetReasons(item, medianMv) }))
    .filter((entry) => entry.reasons.length)
    .sort((a, b) => b.reasons.filter((r) => r[1]).length - a.reasons.filter((r) => r[1]).length
      || a.item.row.hex.localeCompare(b.item.row.hex));
  fui.att.replaceChildren();
  for (const { item, reasons } of list) {
    const li = el("li");
    const button = tagButton(null, item);
    const mark = el("span", `mark ${item.row.failed ? "s-alert" : `s-${item.row.status}`}`);
    const why = el("span", reasons.some((r) => r[1]) ? "why bad" : "why", reasons.map((r) => r[0]).join(" · "));
    button.append(mark, el("span", "mono", item.row.hex), el("span", "dim", item.row.alias || ""), why,
      el("span", "go", "Open"));
    li.append(button);
    fui.att.append(li);
  }
  fui.att.hidden = list.length === 0;
  fui.attNone.hidden = list.length > 0;
  setText(fui.attCount, list.length ? plural(list.length, "tag") : "");
  return new Set(list.map((entry) => entry.item.row.hex));
}

function barRow(item, pct, fillCls, value, valueBad, lines) {
  const button = tagButton("dfl-bar", item);
  const track = el("span", "track");
  const fill = el("span", `fill ${fillCls || ""}`);
  fill.style.width = `${Math.max(0, Math.min(100, pct)).toFixed(1)}%`;
  track.append(fill);
  for (const [at, cls] of lines) {
    const line = el("span", `line ${cls || ""}`);
    line.style.left = `${Math.max(0, Math.min(100, at)).toFixed(1)}%`;
    track.append(line);
  }
  button.append(el("span", "mono", item.row.hex), el("span", "name", item.row.alias || ""), track,
    el("span", valueBad ? "val bad" : "val", value));
  return button;
}

function scaleRow(left, mid, right) {
  const row = el("div", "dfl-scale");
  const ticks = el("span");
  ticks.append(el("span", null, left), el("span", null, mid), el("span", null, right));
  row.append(el("span"), el("span"), ticks, el("span"));
  return row;
}

function renderFleetBattery(items) {
  const low = prefs.low_battery_v;
  const withV = items.filter((item) => item.row.battery != null)
    .sort((a, b) => a.row.battery - b.row.battery);
  const lo = Math.min(2.4, ...withV.map((i) => i.row.battery - 0.05));
  const hi = Math.max(3.2, ...withV.map((i) => i.row.battery + 0.02));
  const at = (v) => ((v - lo) / (hi - lo)) * 100;
  fui.batt.replaceChildren(...withV.map((item) => {
    const v = item.row.battery;
    return barRow(item, at(v), v < low ? "bad" : v < low + 0.15 ? "warn" : "", `${v.toFixed(2)} V`, v < low,
      [[at(low), ""]]);
  }));
  if (withV.length) fui.batt.append(scaleRow(`${lo.toFixed(2)} V`, ((lo + hi) / 2).toFixed(2), `${hi.toFixed(2)} V`));
  const missing = items.length - withV.length;
  setText(fui.battNote, `lowest first · red line: low battery (${low.toFixed(2)} V)`
    + (missing ? ` · ${missing} without a reading` : ""));
}

function renderFleetDrain(items, medianMv) {
  const withD = items.filter((item) => item.mv != null).sort((a, b) => b.mv - a.mv);
  const top = Math.max(5, ...withD.map((item) => item.mv * 1.1));
  const at = (mv) => (mv / top) * 100;
  const tooHigh = (mv) => medianMv > 0 && mv > Math.max(medianMv * 2, medianMv + 3);
  fui.drain.replaceChildren(...withD.map((item) => {
    const mv = item.mv;
    const value = mv < 0 ? `rising ${Math.abs(mv).toFixed(1)}` : `${mv.toFixed(1)} mV/day`;
    return barRow(item, mv < 0 ? 0 : at(mv), tooHigh(mv) ? "bad" : mv < 0 ? "neg" : "", value, tooHigh(mv),
      medianMv != null ? [[at(Math.max(0, medianMv)), "median"]] : []);
  }));
  if (withD.length) fui.drain.append(scaleRow("0", (top / 2).toFixed(1), `${top.toFixed(1)} mV/day`));
  const short = items.length - withD.length;
  setText(fui.drainNote, (medianMv != null ? `highest first · dashed: fleet median (${medianMv.toFixed(1)} mV)` : "highest first")
    + (short ? ` · ${short} with under 6 h of readings` : ""));
}

function renderFleetFirmware(items, data) {
  const running = new Map();
  for (const item of items) {
    if (item.fw) running.set(item.fw, (running.get(item.fw) || 0) + 1);
  }
  const versions = (data?.firmware || []).slice().reverse();          // newest first
  const colour = new Map(versions.map((f, i) => [f.version, `fwc-${Math.min(i, 3)}`]));
  const mix = [...running.entries()].sort((a, b) => (colour.get(a[0]) || "fwc-3").localeCompare(colour.get(b[0]) || "fwc-3"));
  fui.fwMix.replaceChildren(...mix.map(([version, count]) => {
    const part = el("span", colour.get(version) || "fwc-3", `${version} · ${count}`);
    part.style.width = `${(100 * count / items.length).toFixed(1)}%`;
    part.title = `${version}: ${plural(count, "tag")} now`;
    return part;
  }));
  const median = data?.median_drain;
  fui.fw.replaceChildren(...versions.map((f) => {
    const tr = el("tr");
    const name = el("td");
    name.append(el("span", `fw-swatch ${colour.get(f.version)}`), el("span", "mono", f.version));
    const drainBad = f.drain_mv_per_day != null && median > 0 && f.drain_mv_per_day > median * 1.3;
    const pct = f.expected ? ` (${(100 * f.missed / f.expected).toFixed(1)} %)` : "";
    tr.append(
      name,
      el("td", null, `${f.tags.length}${running.get(f.version) ? `, ${running.get(f.version)} now` : ""}`),
      el("td", drainBad ? "num bad" : "num", f.drain_mv_per_day == null ? "under 6 h of readings"
        : drainLabel(f.drain_mv_per_day)),
      el("td", "num", uaLabel(f.ua, f.drain_mv_per_day)),
      el("td", "num", `${f.missed.toLocaleString()}${pct}`),
      el("td", f.pushes_failed ? "num bad" : "num", f.pushes ? `${f.pushes_failed} of ${f.pushes}` : "—"),
      el("td", null, f.first_seen ? fmtWhen(f.first_seen) : "—"),
    );
    if (f.drain_mv_per_day != null) {
      tr.title = `Measured over ${f.measured_h} h on ${plural(f.measured_tags, "tag")}`;
    }
    return tr;
  }));
}

function renderFleetHeat(items, data) {
  const now = data?.now || Date.now() / 1000;
  const day0 = now - 86400;
  const offline = data?.offline || [];
  // how much of each hour nobody was listening
  const hourOff = Array.from({ length: 24 }, (_, i) => {
    const a = day0 + i * 3600, b = a + 3600;
    return offline.reduce((sum, [d0, d1]) => sum + Math.max(0, Math.min(b, d1) - Math.max(a, d0)), 0) / 3600;
  });
  const sorted = items.slice().sort((a, b) => (b.day?.missed || 0) - (a.day?.missed || 0)
    || a.row.hex.localeCompare(b.row.hex));
  fui.heat.replaceChildren(...sorted.map((item) => {
    const button = tagButton("dfl-heat-row", item);
    button.append(el("span", "mono", item.row.hex), el("span", "name", item.row.alias || ""));
    const perHour = 3600 / (item.f?.interval_s || item.row.pollS || 300);
    const hourly = item.day?.hourly || Array(24).fill(0);
    hourly.forEach((missed, i) => {
      let cls = "dh0";
      if (hourOff[i] > 0.9) cls = "dhx";
      else if (missed >= perHour * 0.9) cls = "dh3";
      else if (missed >= 2) cls = "dh2";
      else if (missed === 1) cls = "dh1";
      const cell = el("i", cls);
      const from = new Date((day0 + i * 3600) * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
      cell.title = cls === "dhx" ? `${from}: nobody was listening` : `${from}: ${missed ? `${missed} missed` : "all heard"}`;
      button.append(cell);
    });
    const day = item.day;
    const pct = day?.expected ? 100 * (day.expected - day.missed) / day.expected : null;
    button.append(el("span", pct != null && pct < 95 ? "val bad" : "val", pct == null ? "—" : `${pct.toFixed(1)} %`));
    return button;
  }));
  const axis = el("div", "dfl-axis");
  const ticks = el("span");
  ticks.append(el("span", null, "24 h ago"), el("span", null, "12 h ago"), el("span", null, "now"));
  axis.append(el("span"), el("span"), ticks, el("span"));
  fui.heat.append(axis);
  const off = data?.day_offline_s || 0;
  setText(fui.heatNote, "One square per tag per hour; most missed first."
    + (off > 600 ? ` Nobody was listening for ${spanText(off)} of it (the server or the hub was off): those hours count neither way.` : ""));
}

function fleetSortValue(item, key) {
  const row = item.row;
  switch (key) {
    case "hex": return row.hex;
    case "name": return (row.alias || "").toLowerCase();
    case "shelf": return row.row ?? Infinity;
    case "status": return STATUS_RANK[row.status] ?? 9;
    case "battery": return row.battery ?? Infinity;
    case "drain": return item.mv ?? -Infinity;
    case "current": return item.ua ?? -Infinity;
    case "life": return item.ua > 0 ? -item.ua : -Infinity;
    case "fw": return item.fw || "";
    case "heard": return row.seen ?? Infinity;
    case "missed": return item.checkins?.missed ?? -1;
    case "pushes": return item.pushes?.failed ?? -1;
    default: return 0;
  }
}

function renderFleetTable(items, alerts, medianMv) {
  fui.head.replaceChildren(...DFL_COLUMNS.map(([key, label]) => {
    const th = el("th");
    th.setAttribute("aria-sort", dfl.sort === key ? (dfl.dir > 0 ? "ascending" : "descending") : "none");
    const button = el("button", null, label);
    button.type = "button";
    button.addEventListener("click", () => {
      dfl.dir = dfl.sort === key ? -dfl.dir : 1;
      dfl.sort = key;
      store("dfl.sort", dfl.sort);
      store("dfl.dir", String(dfl.dir));
      dfl.sig = "";
      renderFleetDiag();
    });
    th.append(button);
    return th;
  }));
  for (const button of fui.filter.querySelectorAll("button")) {
    const on = button.dataset.filter === dfl.filter;
    button.classList.toggle("on", on);
    button.setAttribute("aria-pressed", on ? "true" : "false");
    if (button.dataset.filter === "alert") setText(button, `Needs attention (${alerts.size})`);
    if (button.dataset.filter === "all") setText(button, `All (${items.length})`);
  }
  const shown = items.filter((item) => dfl.filter !== "alert" || alerts.has(item.row.hex))
    .sort((a, b) => {
      const x = fleetSortValue(a, dfl.sort), y = fleetSortValue(b, dfl.sort);
      return (x < y ? -1 : x > y ? 1 : 0) * dfl.dir || a.row.hex.localeCompare(b.row.hex);
    });
  const high = (mv) => medianMv > 0 && mv > Math.max(medianMv * 2, medianMv + 3);
  fui.rows.replaceChildren(...shown.map((item) => {
    const { row } = item;
    const tr = el("tr");
    tr.tabIndex = 0;
    tr.title = `Open the diagnostics of ${row.hex}`;
    tr.addEventListener("click", () => openDiagnostics(row.hex));
    tr.addEventListener("keydown", (event) => {
      if (event.key === "Enter") openDiagnostics(row.hex);
    });
    const status = el("td");
    const cell = el("span", "status-cell");
    cell.append(el("span", `mark ${row.failed ? "s-alert" : `s-${row.status}`}`), el("span", null, statusWord(row)));
    status.append(cell);
    const ci = item.checkins;
    tr.append(
      el("td", "num", row.hex),
      el("td", null, row.alias || ""),
      el("td", null, row.row == null ? "None" : shelfName(String(row.row))),
      status,
      el("td", row.low ? "num bad" : "num", row.battery != null ? `${row.battery.toFixed(2)} V` : "—"),
      el("td", item.mv != null && high(item.mv) ? "num bad" : "num", drainLabel(item.mv)),
      el("td", "num", uaLabel(item.ua, item.mv)),
      el("td", null, item.ua > 0 ? diagLifeText(item.ua) : "—"),
      el("td", "num", item.fw || "—"),
      el("td", null, heardText(row)),
      el("td", ci && ci.expected && ci.missed / ci.expected > 0.05 ? "num bad" : "num",
        ci ? `${ci.missed.toLocaleString()} of ${ci.expected.toLocaleString()}` : "—"),
      el("td", item.pushes?.failed ? "num bad" : "num",
        item.pushes?.queued ? `${item.pushes.failed} of ${item.pushes.queued}` : "—"),
    );
    return tr;
  }));
}

function renderFleetDiag() {
  if (screen !== "diagnostics" || diagMode !== "fleet") return;
  const groups = tagsByShelf();
  syncSelect(fui.shelf, "All shelves", groups.map((group) => group.key), (key) => shelfName(key));
  const items = fleetRows();
  const data = dfl.data;
  const signature = JSON.stringify([dfl.loadedAt, dfl.sort, dfl.dir, dfl.filter, prefs.low_battery_v,
    items.map((item) => [item.row.hex, item.row.alias, item.row.status, item.row.battery, item.row.row,
      item.fw, item.row.failed ? 1 : 0, Math.round((item.row.seen || 0) / 60)])]);
  if (signature === dfl.sig) return;
  dfl.sig = signature;
  const medianMv = data?.median_drain ?? null;
  renderFleetKpis(items, data);
  const alerts = renderFleetAttention(items, medianMv);
  renderFleetBattery(items);
  renderFleetDrain(items, medianMv);
  renderFleetFirmware(items, data);
  renderFleetHeat(items, data);
  renderFleetTable(items, alerts, medianMv);
  setText(fui.updated, data ? `Figures from ${new Date(dfl.loadedAt).toLocaleTimeString(undefined,
    { hour: "2-digit", minute: "2-digit" })}` : "Loading the figures");
}

// ── controls ─────────────────────────────────────────────────────────────────
fui.period.value = stored("dfl.period", "7");
if (!fui.period.value) fui.period.value = "7";
fui.period.addEventListener("change", () => {
  store("dfl.period", fui.period.value);
  refreshFleetDiag(true);
});
fui.shelf.addEventListener("change", () => refreshFleetDiag(true));
for (const button of fui.filter.querySelectorAll("button")) {
  button.addEventListener("click", () => {
    dfl.filter = button.dataset.filter;
    store("dfl.filter", dfl.filter);
    dfl.sig = "";
    renderFleetDiag();
  });
}

window.renderFleetDiag = renderFleetDiag;
window.fleetShown = fleetShown;

setInterval(() => {
  if (screen === "diagnostics" && diagMode === "fleet") refreshFleetDiag(true);
}, 60000);

if (screen === "diagnostics" && diagMode === "fleet") fleetShown();
