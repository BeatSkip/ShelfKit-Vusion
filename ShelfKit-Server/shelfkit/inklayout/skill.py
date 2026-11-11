"""The InkLayout skill file: everything a (cheap) model needs to write good layouts.

Generated from the renderer itself - its element/attribute registry, the sharp font
sizes, the icon set, the display preset - so it can never teach something the
renderer does not accept. The examples are rendered while the file is built and
their box pictures are included, and tests/inklayout_test.py checks that every
example renders without a single warning.

    python -m shelfkit.inklayout skill [--display ID] [--orientation landscape] > SKILL.md
    GET /api/layout/skill?display=<id>&orientation=<portrait|landscape>
"""

from __future__ import annotations

from datetime import datetime

from .. import displays
from . import icons
from .engine import ALLOWED_SIZES, ATTRS, FONTS, PATTERNS, _width, render
from ..service_image import font as _font

SAMPLE_TAG = {"hex_id": "0101", "id": "0101", "alias": "Kitchen", "notes": "", "battery": 2.9}
SAMPLE_NOW = datetime(2026, 11, 12, 8, 30)

# What each attribute means, for the reference table. Keep in step with engine.ATTRS
# (a test fails when an attribute has no line here).
ATTR_DOCS = {
    "w": "width: pixels (40), percent of the parent (50%), fill, fill:2, auto (default)",
    "h": "height: same forms as w",
    "bg": "background: a colour, none, or a pattern (checker, dots, hatch; optional colour: 'hatch red')",
    "border": "'<width> <colour>', e.g. '1 black'; drawn inside the box",
    "radius": "rounded corners in pixels",
    "padding": "space inside the box: 4, '4 8' (vertical horizontal) or '2 4 2 4' (top right bottom left)",
    "if": "only shown when this is true, e.g. if=\"data.note\"",
    "id": "a name for your own reference; not drawn",
    "display": "a display preset id; normally left out (the tag's own display is used)",
    "orientation": "portrait (default) or landscape",
    "gap": "pixels between children",
    "align": "cross axis: start, center, end, stretch (default: stretch in col, center in row)",
    "justify": "main axis: start (default), center, end, between",
    "cols": "number of equal columns",
    "cell-h": "height of every grid cell in pixels (default: tallest child)",
    "size": "font size in pixels; snapped to the nearest sharp size",
    "font": f"{' or '.join(FONTS)}",
    "bold": "true for bold",
    "color": "a colour of the display",
    "fit": "ellipsis (default: cut with …), shrink (smaller sizes until it fits), wrap (as many lines as fit)",
    "lines": "maximum number of lines (default 1; with fit=wrap: as many as fit)",
    "name": "the icon's name",
    "value": "the bar's value",
    "max": "the bar's full value (default 1)",
    "width": "line thickness in pixels",
    "dash": "dash length in pixels (0 = solid)",
    "each": "a list (or a count) to repeat for, e.g. each=\"data.items\"",
    "as": "the name for the current item (default item); loop.index, loop.first, loop.last also exist",
}

ELEMENT_DOCS = {
    "screen": "the root, exactly one; a column of its children",
    "col": "children top to bottom",
    "row": "children left to right",
    "grid": "children in equal cells, row by row",
    "stack": "children on top of each other (align: stretch, center, top-left, top-right, "
             "bottom-left, bottom-right, top, bottom, left, right)",
    "text": "words; the only element that shows text",
    "icon": f"a built-in pixel icon, size a multiple of {icons.BASE}",
    "bar": "a horizontal gauge, filled value/max",
    "line": "a rule: horizontal in a col, vertical in a row",
    "spacer": "empty space; h=\"fill\" pushes what follows to the bottom",
    "repeat": "repeats its children for each item of a list; draws nothing itself",
}

EXAMPLES = [
    {
        "title": "Status card",
        "layout": """<screen padding="6" gap="6">
  <row bg="black" padding="4 6" radius="3">
    <text color="white" bold="true" size="16">{{ tag.alias }}</text>
  </row>
  <row justify="between">
    <text size="12">Temperature</text>
    <text size="12" bold="true">{{ data.temp }} °C</text>
  </row>
  <row justify="between">
    <text size="12">Humidity</text>
    <text size="12" bold="true">{{ data.humidity }} %</text>
  </row>
  <line/>
  <text size="11">BATTERY</text>
  <bar h="10" value="{{ data.battery }}" max="100" border="1 black" padding="2"/>
  <spacer h="fill"/>
  <text size="11" align="center">{{ now | date:"%a %d %b %H:%M" }}</text>
</screen>""",
        "data": {"temp": 21.5, "humidity": 48, "battery": 72},
    },
    {
        "title": "To-do list",
        "layout": """<screen padding="6" gap="4">
  <row gap="6">
    <icon name="check"/>
    <text size="16" bold="true">To do</text>
  </row>
  <line/>
  <repeat each="data.items" as="item">
    <row gap="6">
      <icon name="{{ item.done ? 'check' : 'cross' }}" color="{{ item.done ? 'black' : 'red' }}"/>
      <text size="12" w="fill">{{ item.text }}</text>
    </row>
  </repeat>
  <spacer h="fill"/>
  <text size="11" align="right">{{ data.items | count }} items</text>
</screen>""",
        "data": {"items": [{"text": "Water the plants", "done": True},
                           {"text": "Buy coffee", "done": False},
                           {"text": "Call the plumber", "done": False}]},
    },
    {
        "title": "Month grid (pill tracker)",
        "layout": """<screen padding="4" gap="6">
  <row bg="black" padding="4 6" justify="between">
    <text color="white" bold="true" size="16">{{ data.month | upper }}</text>
    <icon name="pill" color="white"/>
  </row>
  <grid cols="7" gap="3" cell-h="15">
    <repeat each="data.days" as="d">
      <stack bg="{{ d.taken ? 'black' : 'white' }}" border="{{ d.today ? '2 red' : '1 black' }}">
        <text size="10" align="center" color="{{ d.taken ? 'white' : 'black' }}">{{ d.n }}</text>
      </stack>
    </repeat>
  </grid>
  <line/>
  <text size="11">LAST TAKEN</text>
  <text size="28" bold="true" color="red">{{ data.last | time:"%H:%M" }}</text>
</screen>""",
        "data": {"month": "November", "last": "2026-11-12T08:02:00",
                 "days": [{"n": i, "taken": i < 12, "today": i == 12} for i in range(1, 29)]},
    },
    {
        "title": "One big number",
        "layout": """<screen padding="8" gap="4">
  <text size="12" bold="true">{{ data.label | upper }}</text>
  <spacer h="fill"/>
  <text size="72" bold="true" align="center" fit="shrink">{{ data.value }}</text>
  <text size="14" align="center">{{ data.unit }}</text>
  <spacer h="fill"/>
  <row bg="checker" h="12"/>
</screen>""",
        "data": {"label": "Steps today", "value": 8412, "unit": "steps"},
    },
    {
        "title": "Message board",
        "layout": """<screen padding="6" gap="6">
  <row gap="6">
    <icon name="message" size="24"/>
    <text size="16" bold="true">Messages</text>
  </row>
  <repeat each="data.messages" as="m">
    <col border="1 black" padding="4" gap="2">
      <text size="11" bold="true">{{ m.from }} · {{ m.at | time:"%H:%M" }}</text>
      <text size="12" fit="wrap" lines="3">{{ m.text }}</text>
    </col>
  </repeat>
</screen>""",
        "data": {"messages": [
            {"from": "Anna", "at": "2026-11-12T07:45:00", "text": "Dinner is in the oven, back at seven."},
            {"from": "Tom", "at": "2026-11-12T08:10:00", "text": "Took the bike, back by noon."}]},
    },
]


def _chars_table(width: int) -> str:
    sample = "The quick brown fox jumps over the lazy dog 0123456789"
    rows = ["| size | regular | bold |", "|---|---|---|"]
    for size in (10, 12, 14, 16, 20, 24, 32, 48):
        counts = []
        for bold in (False, True):
            f = _font(size, bold=bold)
            per = _width(f, sample) / len(sample)
            counts.append(str(int((width - 12) // per)))
        rows.append(f"| {size} | {counts[0]} | {counts[1]} |")
    return "\n".join(rows)


def skill_markdown(display: str | None = None, orientation: str = "portrait") -> str:
    preset = displays.preset(display)
    w, h = sorted((preset.width, preset.height))
    if orientation == "landscape":
        w, h = h, w
    colours = ", ".join(preset.colors)
    out = [f"""---
name: inklayout
description: Design a screen for a {w} x {h} e-ink shelf tag in InkLayout, an XML layout language that always renders sharply. Use when asked to lay out, design or change what a tag shows.
---

# InkLayout for the {preset.name}

You write one `<screen>` document. The renderer does all positioning and measuring,
draws it pixel-sharp, and tells you in words what did not fit.

## The display

- **{w} x {h} pixels**, {orientation}. Colours: **{colours}**. Nothing else exists: no
  grey, no opacity, no gradients. For a grey look use a pattern: {', '.join(PATTERNS)}.
- E-ink: high contrast reads best. Use red for the one thing that needs attention.

## Rules that matter most

1. Never compute positions. Use `<col>`, `<row>`, `<grid>`, `gap`, `padding`, `justify`.
2. Use at most three text sizes on one screen.
3. Give long or unknown text a `fit` (`shrink` or `wrap` with `lines`).
4. Never put text on a pattern: it becomes unreadable. Text on black needs `color="white"`.
5. Use `<spacer h="fill"/>` to push things to the bottom.
6. Fill in data with `{{{{ data.name }}}}`. Hide optional parts with `if="data.name"`.
7. Answer with exactly one complete `<screen>` document in one ```xml block, nothing else.

## Elements
"""]
    for el in ("screen", "col", "row", "grid", "stack", "text", "icon", "bar", "line", "spacer",
               "repeat"):
        attrs = sorted(ATTRS[el] - {"id"})
        out.append(f"- **`<{el}>`**: {ELEMENT_DOCS[el]}. Attributes: "
                   + ", ".join(f"`{a}`" for a in attrs))
    out.append("\n## Attributes\n")
    for attr in sorted({a for v in ATTRS.values() for a in v} - {"id"}):
        out.append(f"- `{attr}`: {ATTR_DOCS[attr]}")

    out.append(f"""
## Text

Sharp sizes: {', '.join(map(str, ALLOWED_SIZES))}. Other sizes are snapped to the nearest.
Fonts: {' and '.join(FONTS)}. How many characters fit across the screen (with 6 px padding):

{_chars_table(w)}

## Data

- `{{{{ data.x }}}}` the app's data, `{{{{ tag.alias }}}}` / `{{{{ tag.id }}}}` the tag,
  `{{{{ now }}}}` the time. Paths: `data.items[0].name`.
- Filters: `| upper`, `| lower`, `| title`, `| time:"%H:%M"`, `| date:"%a %d %b"`,
  `| round:1`, `| int`, `| count`, `| default:"-"`.
- Conditions: `a ? 'x' : 'y'`, `==`, `!=`, `<`, `>`, `<=`, `>=`, `and`, `or`, `not`.
- No arithmetic; ask for the value you need in the data instead.

## Icons

{', '.join(icons.names())}. Sizes: {', '.join(map(str, icons.sizes()))}.

## Examples
""")
    for ex in EXAMPLES:
        r = render(ex["layout"], ex["data"], tag=SAMPLE_TAG, display=preset.id, now=SAMPLE_NOW)
        out.append(f"### {ex['title']}\n\n```xml\n{ex['layout'].strip()}\n```\n\n"
                   f"Rendered as (element, size, position, text shown):\n\n```\n{r.boxes}\n```\n")
    out.append("""## When the renderer answers

You get back a list of problems and the rendered box picture. Fix every `error`
(the layout is not shown otherwise) and every `warn` (text cut, content that does
not fit). `info` is advice. Change only what the problems point at.
""")
    return "\n".join(out)
