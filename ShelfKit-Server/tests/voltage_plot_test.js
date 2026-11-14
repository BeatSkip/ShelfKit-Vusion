"use strict";

// Run with: node tests/voltage_plot_test.js
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const staticDir = path.join(__dirname, "..", "shelfkit", "static");
const app = fs.readFileSync(path.join(staticDir, "app.js"), "utf8");
const diagnostics = fs.readFileSync(path.join(staticDir, "diag.js"), "utf8");
const section = (source, start, end) => source.slice(source.indexOf(start), source.indexOf(end));

class Node {
  constructor(name) { this.name = name; this.attrs = {}; this.children = []; this.textContent = ""; }
  setAttribute(name, value) { this.attrs[name] = String(value); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; }
}

function form() {
  const handlers = {};
  const autoHandlers = {};
  const error = { textContent: "" };
  return {
    elements: { min: { value: "" }, max: { value: "" } },
    addEventListener: (name, fn) => { handlers[name] = fn; },
    querySelector: (selector) => selector === ".voltage-error" ? error : {
      addEventListener: (name, fn) => { autoHandlers[name] = fn; },
    },
    submit: () => handlers.submit({ preventDefault() {} }),
    auto: () => autoHandlers.click(),
    error,
  };
}

function setup(saved = "") {
  const forms = { "diag-voltage-scale": form() };
  const storage = { "voltage.scale": saved };
  const sideChart = new Node("svg"), diagChart = new Node("svg");
  const context = vm.createContext({
    $, document: { createElementNS: (_, name) => new Node(name) },
    stored: (key, fallback) => storage[key] || fallback,
    store: (key, value) => { storage[key] = value; },
    window: {}, prefs: { low_battery_v: 2.5 },
    vui: { chart: sideChart },
    dui: { chart: diagChart, plot: { clientWidth: 700, clientHeight: 400 }, readout: {} },
    diag: { tag: "0100", data: null, runs: [], installs: [[2, "1.1.0-49", "1.1.0-46"]], plot: null },
    setText() {}, drawDiagSelection() {},
    diagTimeLabel: () => "time", fmtTime: () => "time",
  });
  function $(id) { return forms[id]; }
  vm.runInContext(section(app, "function svgEl(", "function fmtTime("), context);
  vm.runInContext(section(app, "function validVoltageRange(", "function fmtWhen("), context);
  vm.runInContext(section(app, "function drawVoltage(", "function drawVoltageStats("), context);
  vm.runInContext(section(diagnostics, "function niceStep(", "/** An axis label"), context);
  vm.runInContext(section(diagnostics, "function drawDiagPlot(", "function drawDiagSelection("), context);
  context.window.drawDiagPlot = () => vm.runInContext("drawDiagPlot()", context);
  return { context, forms, storage, sideChart, diagChart };
}

function descendants(node) {
  return [node, ...node.children.flatMap(descendants)];
}

const { context, forms, storage, sideChart, diagChart } = setup();
context.diag.data = { points: [[1, 2.4], [2, 2.8], [3, 3.2]] };
vm.runInContext("drawVoltage({ points: [[1, 2.4], [2, 2.8], [3, 3.2]] }); drawDiagPlot()", context);
const diag = forms["diag-voltage-scale"];
const sideBefore = JSON.stringify(sideChart);
diag.elements.min.value = "2.6";
diag.elements.max.value = "3.0";
diag.submit();
assert.equal(storage["voltage.scale"], "2.6,3");
{
  const nodes = descendants(diagChart);
  const clipped = nodes.find((node) => node.name === "g" && node.attrs["clip-path"]);
  assert.ok(clipped.children.some((node) => node.attrs.class === "series"));
  assert.ok(nodes.some((node) => node.name === "clipPath"));
  assert.ok(!nodes.some((node) => node.attrs.class === "low-line"));
  // a firmware install inside the window gets a marker with its version
  assert.ok(nodes.some((node) => node.attrs.class === "fw-line"));
  assert.ok(nodes.some((node) => node.attrs.class === "fw-text" && node.textContent === "1.1.0-49"));
}
// the side panel stays on automatic scaling whatever the diagnostics range is
vm.runInContext("drawVoltage({ points: [[1, 2.4], [2, 2.8], [3, 3.2]] })", context);
assert.equal(JSON.stringify(sideChart), sideBefore);
assert.ok(descendants(sideChart).some((node) => node.attrs.class === "low-line"));

diag.elements.min.value = "3";
diag.elements.max.value = "2";
diag.submit();
assert.match(diag.error.textContent, /max at least/);
assert.equal(storage["voltage.scale"], "2.6,3");
diag.elements.min.value = "";
diag.elements.max.value = "3";
diag.submit();
assert.match(diag.error.textContent, /max at least/);
diag.elements.min.value = "2";
diag.elements.max.value = "10.1";
diag.submit();
assert.equal(storage["voltage.scale"], "2.6,3");

diag.elements.min.value = "2.5";
diag.elements.max.value = "2.501";
diag.submit();
assert.equal(storage["voltage.scale"], "2.5,2.501");
{
  const labels = descendants(diagChart).filter((node) => node.name === "text").map((node) => node.textContent);
  assert.ok(labels.some((label) => /^2\.500\d$/.test(label)), "small ranges need four-decimal ticks");
}

assert.equal(setup(storage["voltage.scale"]).forms["diag-voltage-scale"].elements.max.value, 2.501);
diag.auto();
assert.equal(storage["voltage.scale"], "auto");
assert.equal(diag.elements.min.value, "");
assert.equal(setup(",3").forms["diag-voltage-scale"].elements.min.value, "");
console.log("Battery voltage plot tests passed.");
