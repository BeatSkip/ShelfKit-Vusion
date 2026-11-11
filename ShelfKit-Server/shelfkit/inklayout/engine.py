"""InkLayout: parse a <screen> document, lay it out on whole pixels, draw it 1-bit.

See Documentation/InkLayout.md for the language. The pipeline:

    parse    XML -> elements; DOCTYPE/entities refused, sizes capped
    expand   data binding: {{ }}, if=, <repeat>; unknown elements/attributes reported
    measure  natural sizes (text measured exactly as it will be drawn)
    arrange  every node gets an integer rectangle; fill/%/px/auto resolved
    draw     backgrounds, patterns, borders, text, icons, bars - each clipped to
             its parent, so nothing can land outside the box it was given

Every problem becomes a diagnostic (level error/warn/info, the element's path and
a sentence that says what to change); the renderer itself never raises on bad
input. `ok` is False only when there is an error.
"""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime

from PIL import Image, ImageDraw

from .. import displays
from ..service_image import font as _load_font
from . import icons
from .expr import MISSING, ExprError, as_text, evaluate, interpolate

MAX_SOURCE = 64 * 1024
MAX_NODES = 3000

# Font sizes that are drawn without anti-aliasing. To be narrowed per font once the
# fonts are bundled and each size has been checked on a panel (InkLayout.md §6).
ALLOWED_SIZES = (10, 11, 12, 13, 14, 16, 18, 20, 22, 24, 28, 32, 36, 40, 48, 56, 64, 72, 96)
MIN_SHRINK = 10
FONTS = ("sans", "mono")
PATTERNS = ("checker", "dots", "hatch")

COMMON = {"w", "h", "bg", "border", "radius", "padding", "if", "id"}
ATTRS = {
    "screen": COMMON | {"display", "orientation", "gap", "align", "justify"},
    "col": COMMON | {"gap", "align", "justify"},
    "row": COMMON | {"gap", "align", "justify"},
    "grid": COMMON | {"cols", "gap", "cell-h"},
    "stack": COMMON | {"align"},
    "text": COMMON | {"size", "font", "bold", "color", "align", "fit", "lines"},
    "icon": COMMON | {"name", "size", "color"},
    "bar": COMMON | {"value", "max", "color"},
    "line": COMMON | {"color", "width", "dash"},
    "spacer": {"w", "h", "if", "id"},
    "repeat": {"each", "as", "if"},
}
CONTAINERS = {"screen", "col", "row", "grid", "stack"}
ELEMENTS = sorted(ATTRS)


@dataclass
class Node:
    tag: str
    attrs: dict
    path: str
    children: list = field(default_factory=list)
    text: str = ""
    x: int = 0
    y: int = 0
    w: int = 0
    h: int = 0
    axis: str = "col"            # the parent's direction (decides which way a <line> runs)
    shown: list = field(default_factory=list)   # text: the lines actually drawn
    size: int = 0                # text: the size actually used
    ink_y: int | None = None     # text: set when one line is placed by its ink (tight box)


@dataclass
class LayoutResult:
    image: Image.Image
    diagnostics: list
    layout: list                 # [{"path","tag","x","y","w","h",(text,size,lines)}]
    boxes: str                   # the layout as an indented text picture
    display: str

    @property
    def ok(self) -> bool:
        return not any(d["level"] == "error" for d in self.diagnostics)


class _Ctx:
    def __init__(self, preset: displays.DisplayPreset, data_ctx: dict) -> None:
        self.preset = preset
        self.data = data_ctx
        self.diags: list[dict] = []
        self.nodes = 0

    def diag(self, level: str, at: str, msg: str) -> None:
        if not any(d["at"] == at and d["msg"] == msg for d in self.diags):
            self.diags.append({"level": level, "at": at, "msg": msg})

    # ── attribute helpers ──────────────────────────────────────────────────
    def colour(self, node: Node, attr: str, default=None):
        value = (node.attrs.get(attr) or "").strip()
        if not value:
            return default
        if value in ("none", "transparent"):
            return None
        rgb = self.preset.colors.get(value)
        if rgb is None:
            self.diag("error", node.path,
                      f"{attr}=\"{value}\": this display shows only "
                      f"{', '.join(self.preset.colors)}. For a grey look use a pattern: "
                      f"{', '.join(PATTERNS)} (e.g. bg=\"checker\").")
            return default
        return tuple(rgb)

    def fill_spec(self, node: Node, attr: str = "bg"):
        """bg: a colour, a pattern ('checker', 'hatch red') or None."""
        value = (node.attrs.get(attr) or "").strip()
        parts = value.split()
        if parts and parts[0] in PATTERNS:
            ink = self.preset.colors.get(parts[1]) if len(parts) > 1 else \
                self.preset.colors.get("black")
            if ink is None:
                self.diag("error", node.path, f"{attr}=\"{value}\": unknown pattern colour; "
                          f"use one of {', '.join(self.preset.colors)}")
                return None
            return ("pattern", parts[0], tuple(ink))
        rgb = self.colour(node, attr)
        return ("solid", tuple(rgb)) if rgb else None

    def integer(self, node: Node, attr: str, default: int, lo: int = 0, hi: int = 10000) -> int:
        raw = node.attrs.get(attr)
        if raw is None or str(raw).strip() == "":
            return default
        try:
            value = int(float(str(raw).strip()))
        except ValueError:
            self.diag("error", node.path, f"{attr}=\"{raw}\" must be a whole number")
            return default
        if value < lo or value > hi:
            self.diag("warn", node.path, f"{attr}={value} is outside {lo}..{hi}; clamped")
        return max(lo, min(hi, value))

    def number(self, node: Node, attr: str, default: float) -> float:
        raw = node.attrs.get(attr)
        try:
            return float(raw) if raw not in (None, "") else default
        except (TypeError, ValueError):
            self.diag("error", node.path, f"{attr}=\"{raw}\" must be a number")
            return default

    def padding(self, node: Node) -> tuple[int, int, int, int]:
        raw = str(node.attrs.get("padding", "") or "").split()
        try:
            vals = [max(0, int(float(v))) for v in raw]
        except ValueError:
            self.diag("error", node.path, f"padding=\"{node.attrs.get('padding')}\": "
                      "use 1, 2 or 4 whole numbers (all / vertical horizontal / top right bottom left)")
            vals = []
        if not vals:
            return (0, 0, 0, 0)
        if len(vals) == 1:
            return (vals[0],) * 4
        if len(vals) == 2:
            return (vals[0], vals[1], vals[0], vals[1])
        if len(vals) == 4:
            return tuple(vals)
        self.diag("error", node.path, "padding takes 1, 2 or 4 numbers")
        return (0, 0, 0, 0)

    def border(self, node: Node):
        raw = str(node.attrs.get("border", "") or "").split()
        if not raw or raw[0] in ("0", "none"):
            return 0, None
        try:
            width = max(0, int(raw[0]))
        except ValueError:
            self.diag("error", node.path, "border is \"<width> <colour>\", e.g. border=\"1 black\"")
            return 0, None
        colour = raw[1] if len(raw) > 1 else "black"
        rgb = self.preset.colors.get(colour)
        if rgb is None:
            self.diag("error", node.path, f"border colour {colour!r}: use one of "
                      f"{', '.join(self.preset.colors)}")
            return 0, None
        return width, tuple(rgb)

    def size_spec(self, node: Node, attr: str):
        """('px', n) | ('pct', f) | ('fill', weight) | ('auto', None)"""
        raw = str(node.attrs.get(attr, "") or "").strip()
        if raw in ("", "auto"):
            return ("auto", None)
        m = re.fullmatch(r"fill(?::(\d+(?:\.\d+)?))?", raw)
        if m:
            return ("fill", float(m.group(1) or 1))
        m = re.fullmatch(r"(\d+(?:\.\d+)?)%", raw)
        if m:
            return ("pct", float(m.group(1)) / 100.0)
        m = re.fullmatch(r"\d+", raw)
        if m:
            return ("px", int(raw))
        self.diag("error", node.path, f"{attr}=\"{raw}\": use a number of pixels, a percentage "
                  "(50%), fill, fill:2 or auto")
        return ("auto", None)


# ── parse + expand ─────────────────────────────────────────────────────────
def _parse(source: str, ctx: _Ctx):
    if len(source) > MAX_SOURCE:
        ctx.diag("error", "screen", f"the layout is {len(source)} bytes; the limit is {MAX_SOURCE}")
        return None
    if re.search(r"<!(DOCTYPE|ENTITY)", source, re.I):
        ctx.diag("error", "screen", "<!DOCTYPE> and <!ENTITY> are not allowed in a layout")
        return None
    try:
        root = ET.fromstring(source)
    except ET.ParseError as exc:
        ctx.diag("error", "screen", f"the XML is not well-formed: {exc}. Check that every "
                 "element is closed (<text>..</text> or <spacer/>) and & is written &amp;")
        return None
    if root.tag != "screen":
        ctx.diag("error", root.tag, f"the document must start with <screen>, not <{root.tag}>")
        return None
    return root


def _expand(el, ctx: _Ctx, scope: dict, path: str, counters: dict) -> list[Node]:
    tag = el.tag
    if tag not in ATTRS:
        ctx.diag("error", f"{path}/{tag}", f"<{tag}> is not an InkLayout element; use one of "
                 + ", ".join(f"<{e}>" for e in ELEMENTS))
        return []

    cond = el.attrib.get("if")
    if cond is not None:
        try:
            missing: list[str] = []
            value = interpolate(cond, scope, missing) if "{{" in cond else \
                evaluate(cond, scope, missing)
        except ExprError as exc:
            ctx.diag("error", f"{path}/{tag}", f"if=\"{cond}\": {exc}")
            return []
        if not value or value is MISSING:
            return []

    if tag == "repeat":
        each = el.attrib.get("each", "")
        name = el.attrib.get("as", "item")
        try:
            items = interpolate(each, scope) if "{{" in each else evaluate(each, scope)
        except ExprError as exc:
            ctx.diag("error", f"{path}/repeat", f"each=\"{each}\": {exc}")
            return []
        if items is MISSING:
            ctx.diag("warn", f"{path}/repeat", f"each=\"{each}\": no such data; nothing repeated")
            return []
        if isinstance(items, int) and not isinstance(items, bool):
            items = list(range(1, items + 1))
        if not isinstance(items, (list, tuple)):
            ctx.diag("error", f"{path}/repeat", f"each=\"{each}\" must be a list or a count")
            return []
        out = []
        for i, item in enumerate(items):
            inner = dict(scope)
            inner[name] = item
            inner["loop"] = {"index": i + 1, "first": i == 0, "last": i == len(items) - 1}
            for child in el:
                out.extend(_expand(child, ctx, inner, path, counters))
        return out

    ctx.nodes += 1
    if ctx.nodes > MAX_NODES:
        if ctx.nodes == MAX_NODES + 1:
            ctx.diag("error", path, f"more than {MAX_NODES} elements; the rest is left out")
        return []

    counters[tag] = counters.get(tag, 0) + 1
    my_path = f"{path}/{tag}[{counters[tag]}]" if path else tag
    attrs = {}
    for key, raw in el.attrib.items():
        if key not in ATTRS[tag]:
            ctx.diag("warn", my_path, f"<{tag}> has no attribute {key!r}; it is ignored. "
                     f"<{tag}> takes: {', '.join(sorted(ATTRS[tag] - {'if', 'id'}))}")
            continue
        if key == "if":
            continue
        try:
            missing = []
            value = interpolate(raw, scope, missing)
            for m in missing:
                ctx.diag("warn", my_path, f"{key}: no data at {m}")
            attrs[key] = as_text(value)
        except ExprError as exc:
            ctx.diag("error", my_path, f"{key}=\"{raw}\": {exc}")
    node = Node(tag, attrs, my_path)

    if tag == "text":
        raw = "".join(el.itertext())
        try:
            missing = []
            node.text = " ".join(as_text(interpolate(raw, scope, missing)).split())
            for m in missing:
                ctx.diag("warn", my_path, f"no data at {m}: shown as empty. Give it a default "
                         "with | default:\"-\" or hide it with if=")
        except ExprError as exc:
            ctx.diag("error", my_path, f"{raw.strip()!r}: {exc}")
        if len(el):
            ctx.diag("warn", my_path, "<text> holds only text; the elements inside it are ignored")
        return [node]

    if (el.text or "").strip() and tag not in CONTAINERS:
        ctx.diag("warn", my_path, f"<{tag}> shows no text; put words in a <text>")
    child_counters: dict = {}
    for child in el:
        if (child.tail or "").strip():
            ctx.diag("warn", my_path, "loose text between elements is ignored; use <text>")
        node.children.extend(_expand(child, ctx, scope, my_path, child_counters))
    if (el.text or "").strip() and tag in CONTAINERS:
        ctx.diag("warn", my_path, "loose text inside a container is ignored; use <text>")
    if node.children and tag not in CONTAINERS:
        ctx.diag("warn", my_path, f"<{tag}> cannot hold elements; they are ignored")
        node.children = []
    return [node]


# ── text ───────────────────────────────────────────────────────────────────
def _snap(size: int) -> int:
    return min(ALLOWED_SIZES, key=lambda s: (abs(s - size), -s))


def _font(node: Node, ctx: _Ctx, size: int):
    family = node.attrs.get("font", "sans") or "sans"
    if family not in FONTS:
        ctx.diag("warn", node.path, f"font {family!r} is not available; use {' or '.join(FONTS)}")
        family = "sans"
    bold = (node.attrs.get("bold", "") or "").lower() in ("true", "1", "yes", "bold")
    return _load_font(size, mono=family == "mono", bold=bold)


def _ink(f, text: str) -> tuple[int, int]:
    """(left, right) of the ink when drawn 1-bit: the size it really takes."""
    if not text:
        return 0, 0
    try:
        box = f.getbbox(text, mode="1")
    except TypeError:
        box = f.getbbox(text)
    return int(min(0, box[0])), int(box[2])


def _width(f, text: str) -> int:
    left, right = _ink(f, text)
    return right - left


def _ink_v(f, text: str) -> tuple[int, int]:
    """(top, bottom) of the ink below the drawing origin, drawn 1-bit."""
    try:
        box = f.getbbox(text, mode="1")
    except TypeError:
        box = f.getbbox(text)
    return int(box[1]), int(box[3])


def _line_h(f) -> int:
    try:
        ascent, descent = f.getmetrics()
        return int(ascent + descent)
    except AttributeError:
        return int(f.getbbox("Ag")[3]) + 2


def _wrap(f, text: str, width: int, max_lines: int) -> tuple[list[str], bool]:
    """Greedy word wrap; (lines, cut). A word wider than the line is broken."""
    words, lines, cur = text.split(), [], ""
    i = 0
    while i < len(words):
        word = words[i]
        cand = f"{cur} {word}".strip()
        if _width(f, cand) <= width:
            cur, i = cand, i + 1
            continue
        if not cur:                      # one word wider than the line: break it
            k = len(word)
            while k > 1 and _width(f, word[:k]) > width:
                k -= 1
            cur, words[i] = word[:k], word[k:]
        lines.append(cur)
        cur = ""
        if len(lines) == max_lines:
            break
    if cur and len(lines) < max_lines:
        lines.append(cur)
        i = len(words)
    cut = i < len(words) or (len(lines) == max_lines and " ".join(lines) != " ".join(text.split()))
    return lines, cut


def _ellipsis(f, line: str, width: int) -> str:
    while line and _width(f, line + "…") > width:
        line = line[:-1].rstrip()
    return line + "…" if line else ("…" if _width(f, "…") <= width else "")


def _layout_text(node: Node, ctx: _Ctx, width: int, height: int | None, report: bool):
    """Choose size and lines for this width; returns (font, lines, cut, needed_px)."""
    asked = ctx.integer(node, "size", 14, 6, 200)
    size = _snap(asked)
    if report and size != asked:
        ctx.diag("info", node.path, f"size {asked} is not one of the sharp sizes; used {size}. "
                 f"Sharp sizes: {', '.join(map(str, ALLOWED_SIZES))}")
    fit = node.attrs.get("fit", "ellipsis") or "ellipsis"
    if fit not in ("ellipsis", "shrink", "wrap"):
        if report:
            ctx.diag("warn", node.path, f"fit=\"{fit}\": use ellipsis, shrink or wrap")
        fit = "ellipsis"
    default_lines = 99 if fit == "wrap" else 1
    max_lines = ctx.integer(node, "lines", default_lines, 1, 99)
    width = max(1, width)

    candidates = [size]
    if fit == "shrink":
        candidates += [s for s in reversed(ALLOWED_SIZES) if MIN_SHRINK <= s < size]
    chosen = None
    for s in candidates:
        f = _font(node, ctx, s)
        lh = _line_h(f)
        room = max_lines if height is None else max(1, min(max_lines, height // max(1, lh)))
        lines, cut = _wrap(f, node.text, width, room)
        chosen = (f, s, lines, cut)
        if not cut:
            break
    f, s, lines, cut = chosen
    if report and s != size and not cut:
        ctx.diag("info", node.path, f"shrink: size {size} did not fit, used {s}")
    needed = _width(f, node.text)
    if cut and lines:
        lines[-1] = _ellipsis(f, lines[-1], width)
    node.size = s
    return f, lines, cut, needed


# ── measure ────────────────────────────────────────────────────────────────
def _pad(ctx, node):
    t, r, b, left = ctx.padding(node)
    bw, _ = ctx.border(node)
    return t + bw, r + bw, b + bw, left + bw


def _measure(node: Node, ctx: _Ctx, max_w: int) -> tuple[int, int]:
    """Natural (w, h) of a node that may be at most max_w wide."""
    kind_w, val_w = ctx.size_spec(node, "w")
    kind_h, val_h = ctx.size_spec(node, "h")
    if kind_w == "px":
        max_w = min(max_w, val_w)
    elif kind_w == "pct":
        max_w = int(max_w * val_w)
    t, r, b, left = _pad(ctx, node)
    inner = max(0, max_w - left - r)
    tag = node.tag

    if tag == "text":
        f, lines, _, _ = _layout_text(node, ctx, inner, None, report=False)
        w = max((_width(f, ln) for ln in lines), default=0)
        w, h = w, len(lines) * _line_h(f)
    elif tag == "icon":
        s = _icon_size(node, ctx)
        w, h = s, s
    elif tag == "bar":
        w, h = min(inner, 40), 8
    elif tag == "line":
        lw = ctx.integer(node, "width", 1, 1, 20)
        w, h = (lw, 0) if node.axis == "row" else (0, lw)
    elif tag == "spacer":
        w, h = 0, 0
    elif tag in ("col", "screen"):
        gap = ctx.integer(node, "gap", 0)
        sizes = []
        for c in node.children:
            c.axis = "col"
            sizes.append(_measure(c, ctx, inner))
        w = max((s[0] for s in sizes), default=0)
        h = sum(s[1] for s in sizes) + gap * max(0, len(sizes) - 1)
    elif tag == "row":
        gap = ctx.integer(node, "gap", 0)
        sizes = []
        for c in node.children:
            c.axis = "row"
            sizes.append(_measure(c, ctx, inner))
        w = sum(s[0] for s in sizes) + gap * max(0, len(sizes) - 1)
        h = max((s[1] for s in sizes), default=0)
    elif tag == "grid":
        cols, gap = ctx.integer(node, "cols", 2, 1, 64), ctx.integer(node, "gap", 0)
        cell_w = max(1, (inner - gap * (cols - 1)) // cols)
        cell_h = ctx.integer(node, "cell-h", 0) or max(
            (_measure(c, ctx, cell_w)[1] for c in node.children), default=0)
        rows = math.ceil(len(node.children) / cols)
        w, h = inner, rows * cell_h + gap * max(0, rows - 1)
    elif tag == "stack":
        sizes = [_measure(c, ctx, inner) for c in node.children]
        w = max((s[0] for s in sizes), default=0)
        h = max((s[1] for s in sizes), default=0)
    else:
        w, h = 0, 0

    w, h = w + left + r, h + t + b
    if kind_w == "px":
        w = val_w
    if kind_h == "px":
        h = val_h
    return min(w, max_w) if kind_w != "px" else w, h


def _icon_size(node: Node, ctx: _Ctx) -> int:
    s = ctx.integer(node, "size", icons.BASE, 1, 480)
    if s % icons.BASE:
        snapped = max(icons.BASE, round(s / icons.BASE) * icons.BASE)
        ctx.diag("info", node.path, f"icons are drawn at multiples of {icons.BASE} px to stay "
                 f"sharp; size {s} became {snapped}")
        s = snapped
    return s


# ── arrange ────────────────────────────────────────────────────────────────
def _split(total: int, weights: list[float]) -> list[int]:
    """Share total px by weight in whole pixels; the remainder goes to the last share."""
    if not weights:
        return []
    whole = sum(weights)
    out = [int(total * w / whole) for w in weights]
    out[-1] += total - sum(out)
    return out


def _arrange(node: Node, ctx: _Ctx, x: int, y: int, w: int, h: int) -> None:
    node.x, node.y, node.w, node.h = int(x), int(y), max(0, int(w)), max(0, int(h))
    t, r, b, left = _pad(ctx, node)
    ix, iy = node.x + left, node.y + t
    iw, ih = max(0, node.w - left - r), max(0, node.h - t - b)
    tag = node.tag

    if tag == "text":
        f, lines, cut, needed = _layout_text(node, ctx, iw, ih, report=True)
        lh = _line_h(f)
        fit_lines = max(0, ih // lh) if lh else 0
        node.ink_y = None
        if fit_lines == 0 and lines:
            # A full line (ascent + descent) does not fit, but the glyphs themselves
            # may: digits and capitals have no descender. Place the one line by its
            # ink, centred, rather than dropping it (a 2 px border on a 15 px cell).
            top, bottom = _ink_v(f, lines[0])
            if bottom - top <= ih:
                node.ink_y = (ih - (bottom - top)) // 2 - top
                fit_lines = 1
        if len(lines) > fit_lines:
            if fit_lines == 0:
                ctx.diag("warn", node.path, f"text {node.text[:30]!r} has no room: the box is "
                         f"{ih} px high and one line needs {lh} px")
            lines = lines[:fit_lines]
            if lines:
                lines[-1] = _ellipsis(f, lines[-1], iw)
            cut = True
        node.shown = lines
        if cut and node.text:
            shown = " ".join(lines)
            ctx.diag("warn", node.path,
                     f"text {node.text[:40]!r} was cut to {shown[:40]!r} (needs {needed} px, the "
                     f"box is {iw} px wide{'' if len(lines) <= 1 else f' x {len(lines)} lines'}). "
                     "Use fit=\"shrink\", lines=\"2\", a smaller size or a wider box.")
        return

    if tag in ("col", "screen", "row"):
        _arrange_flex(node, ctx, ix, iy, iw, ih, tag == "row")
    elif tag == "grid":
        cols, gap = ctx.integer(node, "cols", 2, 1, 64), ctx.integer(node, "gap", 0)
        cell_w = (iw - gap * (cols - 1)) // cols
        if cell_w < 1:
            ctx.diag("warn", node.path, f"{cols} columns with gap {gap} do not fit in {iw} px")
            cell_w = 1
        cell_h = ctx.integer(node, "cell-h", 0) or max(
            (_measure(c, ctx, cell_w)[1] for c in node.children), default=0)
        rows = math.ceil(len(node.children) / cols) if node.children else 0
        needed = rows * cell_h + gap * max(0, rows - 1)
        if needed > ih:
            ctx.diag("warn", node.path, f"{rows} rows need {needed} px, the grid has {ih} px; "
                     "the last rows are cut. Lower cell-h or the gap, or give the grid more room.")
        for i, c in enumerate(node.children):
            c.axis = "col"
            row, col = divmod(i, cols)
            _arrange(c, ctx, ix + col * (cell_w + gap), iy + row * (cell_h + gap), cell_w, cell_h)
    elif tag == "stack":
        align = node.attrs.get("align", "stretch") or "stretch"
        for c in node.children:
            if align == "stretch":
                _arrange(c, ctx, ix, iy, iw, ih)
                continue
            cw, ch = _measure(c, ctx, iw)
            cw, ch = min(cw, iw), min(ch, ih)
            ax = ix if "left" in align else ix + iw - cw if "right" in align else ix + (iw - cw) // 2
            ay = iy if "top" in align else iy + ih - ch if "bottom" in align else iy + (ih - ch) // 2
            _arrange(c, ctx, ax, ay, cw, ch)


def _arrange_flex(node: Node, ctx: _Ctx, ix, iy, iw, ih, is_row: bool) -> None:
    kids = node.children
    if not kids:
        return
    gap = ctx.integer(node, "gap", 0)
    main_total, cross_total = (iw, ih) if is_row else (ih, iw)
    align = node.attrs.get("align", "center" if is_row else "stretch") or "stretch"
    justify = node.attrs.get("justify", "start") or "start"
    if align not in ("start", "center", "end", "stretch"):
        ctx.diag("warn", node.path, f"align=\"{align}\": use start, center, end or stretch")
        align = "stretch"
    if justify not in ("start", "center", "end", "between"):
        ctx.diag("warn", node.path, f"justify=\"{justify}\": use start, center, end or between")
        justify = "start"

    main_attr, cross_attr = ("w", "h") if is_row else ("h", "w")
    cross: list[int] = []
    main: list[int | None] = []
    weights: dict[int, float] = {}
    autos: list[int] = []
    for i, c in enumerate(kids):
        c.axis = "row" if is_row else "col"
        kind, val = ctx.size_spec(c, cross_attr)
        if kind == "px":
            cs = val
        elif kind == "pct":
            cs = int(cross_total * val)
        elif kind == "fill" or (kind == "auto" and align == "stretch" and c.tag != "icon"):
            cs = cross_total
        else:
            nat = _measure(c, ctx, iw if not is_row else iw)
            cs = nat[1] if is_row else nat[0]
        cs = min(cs, cross_total) if kind != "px" else cs
        cross.append(cs)

        kind, val = ctx.size_spec(c, main_attr)
        if kind == "px":
            main.append(val)
        elif kind == "pct":
            main.append(int(main_total * val))
        elif kind == "fill":
            main.append(None)
            weights[i] = val
        else:
            if is_row:
                main.append(_measure(c, ctx, iw)[0])
            else:
                main.append(_measure(c, ctx, cs)[1])
            autos.append(i)

    fixed = sum(m for m in main if m is not None) + gap * (len(kids) - 1)
    rest = main_total - fixed
    if rest < 0 and is_row and autos:
        # too wide: auto children give up width in proportion (their text is then cut)
        over = -rest
        shrinkable = sum(main[i] for i in autos) or 1
        for i in autos:
            take = min(main[i], math.ceil(over * main[i] / shrinkable))
            main[i] -= take
        fixed = sum(m for m in main if m is not None) + gap * (len(kids) - 1)
        rest = main_total - fixed
    if rest < 0:
        ctx.diag("warn", node.path,
                 f"the content needs {fixed} px {'across' if is_row else 'down'} but the "
                 f"{node.tag} has {main_total} px; what does not fit is cut. Use smaller "
                 "sizes, fewer elements, or h=\"fill\" on the flexible ones.")
    if weights:
        shares = _split(max(0, rest), list(weights.values()))
        for i, s in zip(weights, shares):
            main[i] = s
        rest = 0

    lead, extra_gap = 0, 0
    if rest > 0:
        if justify == "center":
            lead = rest // 2
        elif justify == "end":
            lead = rest
        elif justify == "between" and len(kids) > 1:
            extra_gap = rest // (len(kids) - 1)
            lead = 0
    pos = lead
    for i, c in enumerate(kids):
        m, cs = max(0, main[i]), cross[i]
        if align == "center":
            off = (cross_total - cs) // 2
        elif align == "end":
            off = cross_total - cs
        else:
            off = 0
        if justify == "between" and i == len(kids) - 1 and len(kids) > 1 and rest > 0:
            pos = main_total - m          # the last one sits exactly on the end
        if is_row:
            _arrange(c, ctx, ix + pos, iy + off, m, cs)
        else:
            _arrange(c, ctx, ix + off, iy + pos, cs, m)
        pos += m + gap + extra_gap


# ── draw ───────────────────────────────────────────────────────────────────
def _fill(img: Image.Image, ox: int, oy: int, rect, spec) -> None:
    x0, y0, x1, y1 = rect
    if spec is None or x1 <= x0 or y1 <= y0:
        return
    draw = ImageDraw.Draw(img)
    if spec[0] == "solid":
        draw.rectangle([x0 - ox, y0 - oy, x1 - ox - 1, y1 - oy - 1], fill=spec[1])
        return
    _, kind, ink = spec
    pts = []
    for y in range(y0, y1):           # absolute coordinates: patterns line up across boxes
        for x in range(x0, x1):
            if ((kind == "checker" and (x + y) % 2 == 0)
                    or (kind == "dots" and x % 3 == 0 and y % 3 == 0)
                    or (kind == "hatch" and (x + y) % 4 == 0)):
                pts.append((x - ox, y - oy))
    if pts:
        draw.point(pts, fill=ink)


def _clip(img: Image.Image, ox: int, oy: int, rect):
    """The part of img under rect (absolute coords), clamped to img: (sub, sx, sy) or None."""
    x0, y0, x1, y1 = rect
    lx0, ly0 = max(0, x0 - ox), max(0, y0 - oy)
    lx1, ly1 = min(img.width, x1 - ox), min(img.height, y1 - oy)
    if lx1 <= lx0 or ly1 <= ly0:
        return None
    return img.crop((lx0, ly0, lx1, ly1)), ox + lx0, oy + ly0


def _draw(node: Node, ctx: _Ctx, img: Image.Image, ox: int, oy: int) -> None:
    rect = (node.x, node.y, node.x + node.w, node.y + node.h)
    piece = _clip(img, ox, oy, rect)
    if piece is None:
        return
    sub, sx, sy = piece
    draw = ImageDraw.Draw(sub)
    draw.fontmode = "1"

    radius = ctx.integer(node, "radius", 0, 0, 100)
    spec = ctx.fill_spec(node) if node.tag != "screen" else None
    if spec and radius and spec[0] == "solid":
        draw.rounded_rectangle([node.x - sx, node.y - sy, node.x + node.w - sx - 1,
                                node.y + node.h - sy - 1], radius=radius, fill=spec[1])
    else:
        _fill(sub, sx, sy, rect, spec)
    bw, bcol = ctx.border(node)
    if bw and node.w > 0 and node.h > 0:
        box = [node.x - sx, node.y - sy, node.x + node.w - sx - 1, node.y + node.h - sy - 1]
        if radius:
            draw.rounded_rectangle(box, radius=radius, outline=bcol, width=bw)
        else:
            draw.rectangle(box, outline=bcol, width=bw)

    t, r, b, left = _pad(ctx, node)
    inner = (node.x + left, node.y + t, node.x + node.w - r, node.y + node.h - b)
    tag = node.tag
    if tag == "text":
        _draw_text(node, ctx, sub, sx, sy, inner)
    elif tag == "icon":
        _draw_icon(node, ctx, sub, sx, sy, inner)
    elif tag == "bar":
        _draw_bar(node, ctx, sub, sx, sy, inner)
    elif tag == "line":
        _draw_line(node, ctx, sub, sx, sy, inner)
    elif node.children:
        part = _clip(sub, sx, sy, inner)
        if part is not None:
            psub, px, py = part
            for c in node.children:
                _draw(c, ctx, psub, px, py)
            sub.paste(psub, (px - sx, py - sy))
    img.paste(sub, (sx - ox, sy - oy))


def _draw_text(node, ctx, img, ox, oy, inner) -> None:
    if not node.shown:
        return
    f = _font(node, ctx, node.size)
    colour = ctx.colour(node, "color", tuple(ctx.preset.colors.get("black", (0, 0, 0))))
    draw = ImageDraw.Draw(img)
    draw.fontmode = "1"
    align = node.attrs.get("align", "left") or "left"
    x0, y0, x1, _ = inner
    lh = _line_h(f)
    for i, line in enumerate(node.shown):
        left, right = _ink(f, line)
        width = right - left
        if align == "center":
            x = x0 + (x1 - x0 - width) // 2
        elif align == "right":
            x = x1 - width
        else:
            x = x0
        y = y0 + node.ink_y if node.ink_y is not None else y0 + i * lh
        draw.text((x - left - ox, y - oy), line, font=f, fill=colour)


def _draw_icon(node, ctx, img, ox, oy, inner) -> None:
    name = node.attrs.get("name", "")
    if name not in icons.ICONS:
        ctx.diag("warn", node.path, f"no icon {name!r}; icons: {', '.join(icons.names())}")
        return
    s = _icon_size(node, ctx)
    colour = ctx.colour(node, "color", tuple(ctx.preset.colors.get("black", (0, 0, 0))))
    x0, y0, x1, y1 = inner
    x0 += max(0, (x1 - x0 - s) // 2)
    y0 += max(0, (y1 - y0 - s) // 2)
    pts = [(x0 + px - ox, y0 + py - oy) for px, py in icons.pixels(name, s)]
    ImageDraw.Draw(img).point(pts, fill=colour)


def _draw_bar(node, ctx, img, ox, oy, inner) -> None:
    value, top = ctx.number(node, "value", 0.0), ctx.number(node, "max", 1.0)
    frac = 0.0 if top <= 0 else max(0.0, min(1.0, value / top))
    x0, y0, x1, y1 = inner
    filled = int(round((x1 - x0) * frac))
    colour = ctx.colour(node, "color", tuple(ctx.preset.colors.get("black", (0, 0, 0))))
    if filled > 0 and y1 > y0:
        ImageDraw.Draw(img).rectangle([x0 - ox, y0 - oy, x0 + filled - ox - 1, y1 - oy - 1],
                                      fill=colour)


def _draw_line(node, ctx, img, ox, oy, inner) -> None:
    colour = ctx.colour(node, "color", tuple(ctx.preset.colors.get("black", (0, 0, 0))))
    lw = ctx.integer(node, "width", 1, 1, 20)
    dash = ctx.integer(node, "dash", 0, 0, 50)
    x0, y0, x1, y1 = inner
    draw = ImageDraw.Draw(img)
    if node.axis == "row":                      # vertical rule between items of a row
        x = x0 + max(0, (x1 - x0 - lw) // 2)
        for y in range(y0, y1):
            if dash and (y - y0) // dash % 2:
                continue
            draw.line([(x - ox, y - oy), (x + lw - 1 - ox, y - oy)], fill=colour)
    else:
        y = y0 + max(0, (y1 - y0 - lw) // 2)
        for x in range(x0, x1):
            if dash and (x - x0) // dash % 2:
                continue
            draw.line([(x - ox, y - oy), (x - ox, y + lw - 1 - oy)], fill=colour)


# ── reporting ──────────────────────────────────────────────────────────────
def _collect(node: Node, out: list, lines: list, depth: int = 0) -> None:
    entry = {"path": node.path, "tag": node.tag, "x": node.x, "y": node.y,
             "w": node.w, "h": node.h}
    desc = f"{'  ' * depth}{node.tag} {node.w}x{node.h} @{node.x},{node.y}"
    if node.tag == "text":
        shown = " / ".join(node.shown)
        entry.update(text=shown, size=node.size, lines=len(node.shown))
        bold = " bold" if (node.attrs.get("bold") or "").lower() in ("true", "1", "yes") else ""
        desc += f" '{shown}' ({node.attrs.get('font', 'sans')} {node.size}{bold})"
    elif node.tag == "icon":
        desc += f" {node.attrs.get('name')}"
    if node.attrs.get("bg"):
        desc += f" bg={node.attrs['bg']}"
    out.append(entry)
    lines.append(desc)
    for c in node.children:
        _collect(c, out, lines, depth + 1)


# ── entry point ────────────────────────────────────────────────────────────
def render(source: str, data: dict | None = None, *, tag: dict | None = None,
           display: str | None = None, now: datetime | None = None,
           shared: dict | None = None) -> LayoutResult:
    """Render a <screen> document. Never raises on bad input: see .diagnostics."""
    scope = {"data": data if data is not None else {}, "tag": tag or {},
             "shared": shared or {}, "now": now or datetime.now()}
    preset = displays.preset(display)
    ctx = _Ctx(preset, scope)
    root = _parse(source or "", ctx)

    if root is not None and display is None and root.attrib.get("display"):
        wanted = root.attrib["display"]
        if displays.preset(wanted).id != wanted:
            ctx.diag("warn", "screen", f"display {wanted!r} is unknown; using {preset.id}. "
                     f"Displays: {', '.join(p['id'] for p in displays.presets())}")
        preset = ctx.preset = displays.preset(wanted)

    width, height = preset.width, preset.height
    orientation = root.attrib.get("orientation", "portrait") if root is not None else "portrait"
    if orientation not in ("portrait", "landscape"):
        ctx.diag("warn", "screen", f"orientation=\"{orientation}\": use portrait or landscape")
        orientation = "portrait"
    if orientation == "landscape":
        width, height = max(width, height), min(width, height)
    else:
        width, height = min(width, height), max(width, height)

    white = tuple(preset.colors.get("white", (255, 255, 255)))
    image = Image.new("RGB", (width, height), white)
    layout: list = []
    lines: list = []
    if root is not None:
        nodes = _expand(root, ctx, scope, "", {})
        if nodes:
            screen = nodes[0]
            screen.path = "screen"
            _fix_paths(screen)
            bg = ctx.fill_spec(screen)
            _fill(image, 0, 0, (0, 0, width, height), bg)
            _measure(screen, ctx, width)
            _arrange(screen, ctx, 0, 0, width, height)
            _draw(screen, ctx, image, 0, 0)
            _collect(screen, layout, lines)
    return LayoutResult(image=image, diagnostics=ctx.diags, layout=layout,
                        boxes="\n".join(lines), display=preset.id)


def _fix_paths(node: Node) -> None:
    """Paths are 'screen/col[1]/text[2]' from the root down."""
    counters: dict = {}
    for c in node.children:
        counters[c.tag] = counters.get(c.tag, 0) + 1
        c.path = f"{node.path}/{c.tag}[{counters[c.tag]}]"
        _fix_paths(c)
