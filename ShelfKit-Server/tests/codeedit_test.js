// node tests/codeedit_test.js - the Develop screen's highlighter and code lookups (static/codeedit.js)
"use strict";
const assert = require("assert");
const fs = require("fs");
const path = require("path");

global.window = {};
require(path.join(__dirname, "..", "shelfkit", "static", "codeedit.js"));
const C = window.CodeEdit;
const plain = (html) => html.replace(/<[^>]+>/g, "").replace(/&lt;/g, "<").replace(/&gt;/g, ">")
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&");

// the highlighted layer must hold exactly the text, or it drifts from the caret
const apps = path.join(__dirname, "..", "inkapps");
let checked = 0;
for (const app of fs.readdirSync(apps)) {
  const dir = path.join(apps, app);
  if (!fs.statSync(dir).isDirectory()) continue;
  for (const f of fs.readdirSync(dir)) {
    if (!/\.(py|xml|json|md)$/.test(f)) continue;
    const text = fs.readFileSync(path.join(dir, f), "utf8");
    assert.strictEqual(plain(C.highlight(C.lang(f), text)), text + "\n", `${app}/${f} round-trips`);
    checked++;
  }
}
assert.ok(checked >= 4, "found the example apps");
for (const [lang, text] of [["python", 'x = """open\nstring'], ["python", "s = 'a\\'b' # c"],
  ["xml", '<screen><text a="{{ data.x | default:"-" }}">&amp; {{ data.y</text>'], ["xml", "<!-- open"],
  ["json", '{"a": [1, true, null, "x"]}']]) {
  assert.strictEqual(plain(C.highlight(lang, text)), text + "\n", `odd ${lang} round-trips`);
}

const py = C.highlight("python", '@app.every(minutes=5)\ndef go(tag):\n    return None  # x');
assert.ok(py.includes('tk-deco">@app.every') && py.includes('tk-fn">go') && py.includes('tk-com"># x'));
assert.ok(C.highlight("xml", "<text>{{ data.n }}</text>").includes('tk-ref">data.n'));

const lay = '<screen>\n  <row>\n    <text>{{ data.n }}</text>\n    <txt>x</txt>\n  </row>\n  <text bogus="1">hi</text>\n</screen>';
assert.strictEqual(C.xmlLine(lay, "screen/row[1]/text[1]"), 3);
assert.strictEqual(C.xmlLine(lay, "screen/row[1]/txt"), 4);
assert.strictEqual(C.xmlLine(lay, "screen/text[1]"), 6);

const src = 'app = InkApp("x", layout="layout.xml")\n\n@app.data\ndef data(tag):\n    return {"n": helper()}\n\ndef helper():\n    return 1\n';
const files = { "app.py": src, "layout.xml": lay };
assert.deepStrictEqual(C.definition(files, "layout.xml", lay, lay.indexOf("data.n") + 6).line, 5, "data.n -> app.py");
assert.strictEqual(C.definition(files, "app.py", src, src.indexOf('"n"') + 1).file, "layout.xml", "key -> layout");
assert.strictEqual(C.definition(files, "app.py", src, src.indexOf("helper()") + 1).line, 7, "call -> def");
assert.strictEqual(C.definition(files, "app.py", src, src.indexOf("layout.xml") + 3).file, "layout.xml");
assert.ok(!C.definition(files, "layout.xml", lay, lay.indexOf("bogus")).file);

assert.deepStrictEqual(C.outline("python", src).map((o) => [o.label, o.kind]),
  [["app", "InkApp"], ["data", "data"], ["helper", "def"]]);

const linked = C.linkRefs("KeyError (app.py line 12); line 3, column 15; other.py line 2", ["app.py", "layout.xml"], "layout.xml");
assert.ok(linked.includes('data-goto="app.py:12">app.py line 12</button>'));
assert.ok(linked.includes('data-goto="layout.xml:3:15"'));
assert.ok(!linked.includes("other.py:2"), "only the app's own files are links");
assert.ok(!C.linkRefs("<b>", []).includes("<b>"), "messages are escaped");

console.log(`Code editor tests passed (${checked} app files round-trip).`);
