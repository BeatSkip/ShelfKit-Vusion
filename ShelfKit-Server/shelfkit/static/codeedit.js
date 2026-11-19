"use strict";

/* Code helpers for the Develop screen, with no libraries (the server may have no
 * internet): syntax highlighting for Python and InkLayout XML, an outline of a file,
 * finding where things are defined, and turning "app.py line 12" in any message into a
 * link. develop.js draws the editor; this file only works on text.
 *
 *   CodeEdit.lang(name)                        "python" | "xml" | "json" | "text"
 *   CodeEdit.highlight(lang, text)             HTML for the layer under the textarea
 *   CodeEdit.outline(lang, text)               [{label, kind, line, depth}]
 *   CodeEdit.xmlLine(text, "screen/row[1]/text[1]")   1-based line of that element
 *   CodeEdit.wordAt(text, pos)                 {word, start, end} (dots included)
 *   CodeEdit.definition(files, file, text, pos)   {file, line, col?, note} or {note}
 *   CodeEdit.linkRefs(text, files, fallback)   escaped HTML with [data-goto] buttons
 */
(function () {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const span = (cls, s) => `<span class="tk-${cls}">${esc(s)}</span>`;

  function lang(name) {
    if (/\.py$/.test(name)) return "python";
    if (/\.xml$/.test(name)) return "xml";
    if (/\.json$/.test(name)) return "json";
    if (/\.(md|toml|txt|sprite)$/.test(name)) return "text";
    return "text";
  }
  const LANG_NAME = { python: "Python", xml: "InkLayout XML", json: "JSON", text: "Plain text" };

  // ── Python ───────────────────────────────────────────────────────────────
  const PY_KW = new Set(("and as assert async await break class continue def del elif else except finally for " +
    "from global if import in is lambda nonlocal not or pass raise return try while with yield match case").split(" "));
  const PY_CONST = new Set(["True", "False", "None"]);
  const PY_BI = new Set(("abs all any bool dict enumerate filter float format getattr hasattr int isinstance " +
    "len list map max min next open print range repr round set sorted str sum super tuple type zip " +
    "Exception ValueError KeyError TypeError RuntimeError").split(" "));
  const PY_SELF = new Set(["self", "tag", "app", "canvas", "cls"]);
  const PY = new RegExp([
    /(#[^\n]*)/.source,                                                          // 1 comment
    /((?:[rRbBuUfF]{1,2})?(?:"""[\s\S]*?(?:"""|$)|'''[\s\S]*?(?:'''|$)|"(?:\\.|[^"\\\n])*"?|'(?:\\.|[^'\\\n])*'?))/.source, // 2 string
    /(@[A-Za-z_][\w.]*)/.source,                                                 // 3 decorator
    /\b(0[xXoObB][\da-fA-F_]+|\d[\d_]*(?:\.\d*)?(?:[eE][+-]?\d+)?j?)\b/.source, // 4 number
    /\b([A-Za-z_]\w*)\b/.source,                                                 // 5 name
  ].join("|"), "g");

  function highlightPython(text) {
    let out = "", last = 0, prev = "", m;
    PY.lastIndex = 0;
    while ((m = PY.exec(text))) {
      out += esc(text.slice(last, m.index));
      last = PY.lastIndex;
      if (m[1] !== undefined) out += span("com", m[1]);
      else if (m[2] !== undefined) out += span(/^[rRbBuU]?[fF]|^[fF]/.test(m[2]) ? "fstr" : "str", m[2]);
      else if (m[3] !== undefined) out += span("deco", m[3]);
      else if (m[4] !== undefined) out += span("num", m[4]);
      else {
        const w = m[5];
        const cls = prev === "def" ? "fn" : prev === "class" ? "cls"
          : PY_KW.has(w) ? "kw" : PY_CONST.has(w) ? "const" : PY_BI.has(w) ? "bi"
            : PY_SELF.has(w) ? "self" : text[PY.lastIndex] === "(" ? "call" : null;
        out += cls ? span(cls, w) : esc(w);
        prev = w;
        continue;
      }
      prev = "";
    }
    return out + esc(text.slice(last));
  }

  // ── InkLayout XML ────────────────────────────────────────────────────────
  // expressions: {{ data.x | default:"-" }}; the names data, tag, shared, now stand out
  function highlightExpr(expr) {
    return expr.replace(/("[^"]*"?|'[^']*'?)|\b(data|tag|shared|now)\b((?:\.\w+)*)|(\|\s*\w+)|([^"'|]+?)(?=["']|\b(?:data|tag|shared|now)\b|\||$)/g,
      (all, str, root, rest, filt, other) => {
        if (str !== undefined) return span("str", str);
        if (root !== undefined) return span("ref", root + (rest || ""));
        if (filt !== undefined) return span("filt", filt);
        return esc(other ?? all);
      });
  }
  function textWithExpr(text, cls) {
    let out = "", last = 0;
    const re = /\{\{[\s\S]*?(?:\}\}|$)|&[#\w]+;/g;
    let m;
    while ((m = re.exec(text))) {
      const before = text.slice(last, m.index);
      out += cls ? (before ? span(cls, before) : "") : esc(before);
      if (m[0][0] === "&") out += span("ent", m[0]);
      else {
        const close = m[0].endsWith("}}");
        out += span("brace", "{{") + highlightExpr(m[0].slice(2, close ? -2 : undefined)) + (close ? span("brace", "}}") : "");
      }
      last = re.lastIndex;
      if (!m[0]) re.lastIndex++;
    }
    const tail = text.slice(last);
    return out + (cls ? (tail ? span(cls, tail) : "") : esc(tail));
  }

  function highlightXml(text) {
    let out = "", i = 0;
    while (i < text.length) {
      if (text.startsWith("<!--", i)) {
        const end = text.indexOf("-->", i + 4);
        const stop = end < 0 ? text.length : end + 3;
        out += span("com", text.slice(i, stop));
        i = stop;
        continue;
      }
      const lt = text.indexOf("<", i);
      if (lt !== i) {
        const stop = lt < 0 ? text.length : lt;
        out += textWithExpr(text.slice(i, stop), null);
        i = stop;
        continue;
      }
      const head = /^<(\/?)([A-Za-z_][\w:.-]*)?/.exec(text.slice(i, i + 80));
      if (!head || !head[2]) { out += esc("<"); i++; continue; }
      out += span("punct", "<" + head[1]) + span("tag", head[2]);
      i += head[0].length;
      // attributes until > or />
      while (i < text.length && text[i] !== ">" && !text.startsWith("/>", i)) {
        const rest = text.slice(i);
        const ws = /^\s+/.exec(rest);
        if (ws) { out += esc(ws[0]); i += ws[0].length; continue; }
        const name = /^[A-Za-z_][\w:.-]*/.exec(rest);
        if (name) { out += span("attr", name[0]); i += name[0].length; continue; }
        if (rest[0] === "=") { out += span("punct", "="); i++; continue; }
        if (rest[0] === '"' || rest[0] === "'") {
          const q = rest[0];
          const end = text.indexOf(q, i + 1);
          const stop = end < 0 ? text.length : end + 1;
          out += span("val", q) + textWithExpr(text.slice(i + 1, end < 0 ? text.length : end), "val") +
            (end < 0 ? "" : span("val", q));
          i = stop;
          continue;
        }
        if (rest[0] === "<") break;
        out += esc(rest[0]);
        i++;
      }
      if (text.startsWith("/>", i)) { out += span("punct", "/>"); i += 2; }
      else if (text[i] === ">") { out += span("punct", ">"); i++; }
    }
    return out;
  }

  function highlightJson(text) {
    return text.replace(/("(?:\\.|[^"\\])*")(\s*:)?|\b(true|false|null)\b|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|([^"\d\-tfn]+|[\s\S])/g,
      (all, str, colon, lit, num, other) => {
        if (str !== undefined) return span(colon ? "attr" : "str", str) + esc(colon || "");
        if (lit !== undefined) return span("const", lit);
        if (num !== undefined) return span("num", num);
        return esc(other ?? all);
      });
  }

  function highlight(language, text) {
    // a trailing newline needs a character after it, or the layer is a line short
    const body = language === "python" ? highlightPython(text) : language === "xml" ? highlightXml(text)
      : language === "json" ? highlightJson(text) : esc(text);
    return body + "\n";
  }

  // ── where things are ─────────────────────────────────────────────────────
  const lineAt = (text, pos) => text.slice(0, pos).split("\n").length;

  // the elements of an XML document with their lines, as a tree
  function xmlTree(text) {
    const root = { name: "", children: [], line: 1 };
    const stack = [root];
    const re = /<!--[\s\S]*?-->|<(\/?)([A-Za-z_][\w:.-]*)((?:\s+[^>]*?)?)(\/?)>/g;
    let m;
    while ((m = re.exec(text))) {
      if (!m[2]) continue;
      if (m[1]) {                                  // </name>
        for (let k = stack.length - 1; k > 0; k--) {
          if (stack[k].name === m[2]) { stack.length = k; break; }
        }
        continue;
      }
      const node = { name: m[2], children: [], line: lineAt(text, m.index), attrs: m[3] };
      stack[stack.length - 1].children.push(node);
      if (!m[4]) stack.push(node);
    }
    return root;
  }

  // "screen/row[1]/text[1]": the n-th <row> under <screen>, ... (1-based; no index = the first)
  function xmlLine(text, path) {
    let node = xmlTree(text);
    let line = null;
    for (const part of String(path || "").split("/")) {
      const m = /^([A-Za-z_][\w:.-]*)(?:\[(\d+)\])?$/.exec(part);
      if (!m) break;
      const same = node.children.filter((c) => c.name === m[1]);
      const next = same[(Number(m[2]) || 1) - 1] || same[0];
      if (!next) break;
      node = next;
      line = node.line;
    }
    return line;
  }

  function outline(language, text) {
    const out = [];
    if (language === "python") {
      const lines = text.split("\n");
      let deco = [];
      lines.forEach((l, idx) => {
        const d = /^\s*@([\w.]+)(\(.*)?/.exec(l);
        if (d) { deco.push(d[1].replace(/^app\./, "")); return; }
        const f = /^(\s*)(?:async\s+)?(def|class)\s+(\w+)/.exec(l);
        if (f) {
          out.push({ label: f[3], kind: deco.length ? deco.join(" ") : f[2], line: idx + 1 - deco.length,
            depth: f[1].length ? 1 : 0 });
        } else if (/^(\w+)\s*=\s*InkApp\(/.test(l)) {
          out.push({ label: /^(\w+)/.exec(l)[1], kind: "InkApp", line: idx + 1, depth: 0 });
        } else if (/^\s*app\.(config_field|setting)\(\s*["']([\w-]+)/.test(l)) {
          out.push({ label: /["']([\w-]+)/.exec(l)[1], kind: "setting", line: idx + 1, depth: 0 });
        }
        if (l.trim() && !d) deco = [];
      });
    } else if (language === "xml") {
      const walk = (node, depth) => {
        for (const c of node.children) {
          const ifs = /\bif="([^"]*)"/.exec(c.attrs || "");
          const each = /\beach="([^"]*)"/.exec(c.attrs || "");
          out.push({ label: `<${c.name}>`, kind: ifs ? `if ${ifs[1]}` : each ? `each ${each[1]}` : "",
            line: c.line, depth });
          if (depth < 4) walk(c, depth + 1);
        }
      };
      walk(xmlTree(text), 0);
    }
    return out;
  }

  function wordAt(text, pos) {
    let start = pos, end = pos;
    while (start > 0 && /[\w.]/.test(text[start - 1])) start--;
    while (end < text.length && /[\w.]/.test(text[end])) end++;
    return { word: text.slice(start, end).replace(/^\.+|\.+$/g, ""), start, end };
  }

  function findLine(text, re) {
    const m = re.exec(text);
    return m ? { line: lineAt(text, m.index), col: m.index - text.lastIndexOf("\n", m.index - 1) } : null;
  }
  const reEsc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

  // Ctrl+click: where is the thing under the caret defined (or, for a key set in
  // app.py, where does the layout use it)? files: {name: text}
  function definition(files, file, text, pos) {
    const { word } = wordAt(text, pos);
    if (!word) return { note: "Nothing to look up here" };
    const py = files["app.py"] || "";
    const xml = Object.keys(files).find((n) => n.endsWith(".xml"));
    const parts = word.split(".");

    if (file.endsWith(".xml")) {
      if (parts[0] === "data" && parts[1]) {
        const key = parts[1];
        const hit = findLine(py, new RegExp(`["']${reEsc(key)}["']\\s*:`)) ||
          findLine(py, new RegExp(`\\[\\s*["']${reEsc(key)}["']\\s*\\]\\s*=`)) ||
          findLine(py, new RegExp(`["']${reEsc(key)}["']`));
        return hit ? { file: "app.py", ...hit, note: `data.${key} is set in app.py` }
          : { note: `app.py never names "${key}": the layout shows it empty` };
      }
      if (parts[0] === "shared" && parts[1]) {
        const hit = findLine(py, new RegExp(`shared\\[\\s*["']${reEsc(parts[1])}["']`));
        return hit ? { file: "app.py", ...hit, note: `shared.${parts[1]} is set in app.py` }
          : { note: `app.py never sets shared["${parts[1]}"]` };
      }
      if (parts[0] === "tag") return { note: `${word} comes from the tag itself (alias, notes, battery, config)` };
      if (parts[0] === "now") return { note: "now is the time the screen is drawn for (Pretend it is, on the right)" };
      return { note: `${word}: not a reference` };
    }

    if (file.endsWith(".py")) {
      const name = parts[parts.length - 1];
      // a layout file named in a string
      const around = text.slice(Math.max(0, pos - 40), pos + 40);
      const fileRef = Object.keys(files).find((n) => n !== file && around.includes(n));
      if (fileRef && new RegExp(`["']${reEsc(fileRef)}["']`).test(around)) {
        return { file: fileRef, line: 1, note: `Opened ${fileRef}` };
      }
      const def = findLine(text, new RegExp(`^[ \\t]*(?:async[ \\t]+)?(?:def|class)[ \\t]+${reEsc(name)}\\b`, "m"));
      if (def) return { file, ...def, note: `${name} is defined on line ${def.line}` };
      const assign = findLine(text, new RegExp(`^${reEsc(name)}\\s*=`, "m"));
      if (assign) return { file, ...assign, note: `${name} is set on line ${assign.line}` };
      // a string key: where does the layout use it?
      const quoted = new RegExp(`["']${reEsc(name)}["']`).test(text.slice(Math.max(0, pos - name.length - 2), pos + name.length + 2));
      if (quoted && xml) {
        const use = findLine(files[xml], new RegExp(`\\bdata\\.${reEsc(name)}\\b`));
        return use ? { file: xml, ...use, note: `data.${name} is used in ${xml}` }
          : { note: `${xml} does not use data.${name}` };
      }
      if (/^(tag|app|canvas)$/.test(parts[0]) && parts.length > 1) {
        return { note: `${word}: part of the InkServices SDK (shelfkit/inkservices/sdk.py)` };
      }
      return { note: `No definition of ${name} in this app` };
    }
    return { note: "Go to definition works in app.py and layout files" };
  }

  // "app.py line 12", 'File "...\app.py", line 12', "line 3, column 15" -> links
  function linkRefs(text, files, fallback) {
    const known = new Set(files || []);
    let html = esc(text);
    html = html.replace(/([\w.-]+\.(?:py|xml))(&quot;)?,? line (\d+)/g, (all, name, q, line) =>
      known.has(name) ? `<button type="button" class="code-ref" data-goto="${esc(name)}:${line}">${all}</button>` : all);
    if (fallback && known.has(fallback)) {
      html = html.replace(/(^|[^>\w])line (\d+), column (\d+)/g, (all, pre, line, col) =>
        `${pre}<button type="button" class="code-ref" data-goto="${esc(fallback)}:${line}:${col}">line ${line}, column ${col}</button>`);
    }
    return html;
  }

  window.CodeEdit = { lang, LANG_NAME, highlight, outline, xmlLine, wordAt, definition, linkRefs, lineAt, esc };
})();
