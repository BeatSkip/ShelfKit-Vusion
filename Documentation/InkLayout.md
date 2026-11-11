# InkLayout: a screen description language for e-ink tags

InkLayout is an SVG-like markup for a tag's screen. It is designed so that a cheap AI
model can write it, and so that whatever it writes renders sharply on the panel.

- **The model describes structure** (rows, columns, a grid of pills, a big number with
  a label under it), never pixel positions. The layout engine does the arithmetic.
  Cheap models are good at markup and bad at arithmetic.
- **Sharpness is the renderer's job, not the author's.** Every coordinate is a whole
  pixel, every colour is one the panel has, and text is drawn 1-bit in fonts that the
  project ships. Text never leaves its box. There is no input that renders blurry.
- **Layouts are data, not code.** A layout can't read files, open sockets or run
  anything, so AI-written layouts are safe to render without the safety review that
  AI-written Python needs (InkServices chunk 8).
- **The renderer answers in words as well as pictures.** Each render returns a list of
  problems (text cut off, a box squeezed to nothing, an unknown icon) in plain
  sentences, so even a model without vision can fix its own layout.

An InkService app pairs a layout (how the screen looks) with Python (what the data is).
The app's `render` becomes "fill in this layout with this data". Python drawing on a
`Canvas` stays available for anything the language can't express.

---

## 1. Why the output is always sharp

| Problem on e-ink | How InkLayout rules it out |
|---|---|
| Anti-aliased text breaks into ragged strokes when reduced to 2–3 colours | All text is drawn 1-bit (`fontmode "1"`), measured the same way it is drawn, at whole-pixel positions |
| A font that is fine on one server and different on another | The fonts ship in the repo (§6). No system-font fallback for layouts, so the same layout renders identically on every server |
| Font sizes where hinting looks poor | Each font has a list of **allowed sizes**, checked by eye on the panel. Any other size snaps to the nearest allowed one, with a note in the diagnostics |
| Half-pixel positions blurring edges | The layout engine works in integers only. Percentages and `fill` are resolved to whole pixels, and remainders go to the last child |
| Colours the panel lacks (grey, orange, opacity) | Only the display preset's colour names are accepted. "Grey" exists only as **patterns** (`checker`, `dots`, `hatch`) aligned to the pixel grid, which look the same on screen and on the tag |
| Scaled bitmaps | Icons are pixel-drawn at fixed sizes and scaled only by whole factors (×2, ×3). Photos are dithered explicitly, in their own box |
| Text overflowing its box | Every text element has a fit rule: `ellipsis` (default), `shrink` (steps down the allowed sizes, then ellipsis) or `wrap` with `lines=`. Overflow is impossible, and cut text is reported |
| Preview differing from the tag | The renderer's output already uses only panel colours, so the push pipeline's threshold step changes nothing. The preview is exactly what the tag shows, which a test asserts |

---

## 2. The language

XML, because small models write it reliably (it looks like HTML and SVG) and it is
easy to validate strictly. No DOCTYPE, entities, namespaces or scripts: the parser
rejects them.

### Root

```xml
<screen display="vusion-2.6-bwr" orientation="portrait" bg="white" padding="4">
  ...
</screen>
```

- `display`: a preset id (`shelfkit/displays.py`). Optional: the tag's own preset is
  used when it is left out, so one layout serves every display it fits.
- `orientation`: `portrait` | `landscape`. The pipeline rotates the image to the panel.

### Sizes

On any element, `w` and `h` accept:
- a number of pixels: `40`
- a percentage of the parent: `50%`
- `fill`: share the remaining space. `fill:2` takes twice the share of a plain `fill`.
- `auto`: the content's size. This is the default.

`gap`, `padding` and `margin` take whole pixels (`padding="4"` or `padding="4 8"`).
Negative values are rejected.

### Containers

| Element | What it does | Key attributes |
|---|---|---|
| `<col>` | Children top to bottom | `gap`, `align` (start/center/end/stretch), `justify` (start/center/end/between) |
| `<row>` | Children left to right | same |
| `<grid>` | Equal cells, row by row | `cols`, `gap`, `cell-h` |
| `<stack>` | Children on top of each other (badges, overlays) | `align` |

Every element also takes:
- `bg` (a colour or pattern), and `border="1 black"`
- `radius` (1-bit corners), `padding`, `w`/`h`
- `if="data.path"`

### Content

| Element | What it draws | Key attributes |
|---|---|---|
| `<text>` | A line or paragraph | `size`, `font` (sans/mono/pixel), `bold`, `color`, `align`, `fit` (ellipsis/shrink/wrap), `lines` |
| `<icon>` | A built-in pixel icon | `name`, `size` (one of the icon's drawn sizes), `color` |
| `<bar>` | A horizontal gauge | `value`, `max`, `color`, `bg` |
| `<line>` | A rule | `color`, `width`, `dash` |
| `<spacer>` | Empty space | `w`, `h` (`fill` pushes the following content to the end) |
| `<image>` | A picture the app supplies | `src` (a key in the app's data), `dither` (threshold/floyd/ordered) |

`<rect>`, `<circle>` and `<path>` from SVG are deliberately absent at first. They are
what invites a model to compute coordinates. They can be added later inside a
`<canvas w h>` element with its own local coordinates, if a real need shows up.

### Data, repetition and conditions

The app supplies a JSON-like dict, and the layout reads from it. This is not a
programming language: there are dotted paths and a few filters, and nothing else.

```xml
<text>{{ tag.alias | upper }}</text>
<text>{{ data.last_taken | time:"%a %H:%M" }}</text>
<grid cols="7" gap="2">
  <repeat each="data.days" as="d">
    <col h="16" bg="{{ d.taken ? 'black' : 'white' }}" border="1 black"/>
  </repeat>
</grid>
<text if="data.message" fit="wrap" lines="3">{{ data.message }}</text>
```

- **Paths:** `tag.*` (id, alias, battery), `data.*` (the app's data), `now`.
- **Filters:** `upper`, `lower`, `time:"fmt"`, `date:"fmt"`, `round:n`, `default:"x"`, `count`.
- **The one conditional form:** `a ? 'x' : 'y'`.
- **A missing path renders empty** and is reported in the diagnostics. It never stops the render.

### Colours and patterns

These are the preset's names, which for today's panel are `black`, `white` and `red`.
The patterns are `checker`, `dots` and `hatch`, optionally in a colour (`checker red`).
Anything else is an error that says which colours the display has.

---

## 3. The renderer's answer

```json
{
  "ok": true,
  "png": "<base64 or a URL>",
  "size": [152, 296],
  "diagnostics": [
    {"level": "warn", "at": "screen/col[1]/text[2]",
     "msg": "text 'Wednesday 12 November' was cut to 'Wednesday 12 No…' (needs 131 px, box is 96 px). Use fit=\"shrink\", a smaller size, or a wider box."},
    {"level": "warn", "at": "screen/grid[1]",
     "msg": "7 columns of at least 16 px plus gaps need 124 px, the grid has 112 px; cells were made 14 px."},
    {"level": "info", "at": "screen/text[1]", "msg": "size 15 is not drawn sharply in 'sans'; used 14."}
  ],
  "boxes": "screen 152x296\n  col 144x288 @4,4\n    text 'MAANDAG' 144x18 @4,4 (bold 16)\n    ..."
}
```

`boxes` is a text picture of the result: each element with its resolved size and
position, and the text that actually fitted. A model without vision reads it the way
a person reads the preview.

---

## 4. The model loop (cheap model + skill file)

```
user: "show the pill strip for this month, today's pill red, last taken time at the bottom"
  └─> server builds the prompt:
        system  = the InkLayout skill file (§5), generated for this display preset
        context = the app's data shape with sample values, the current layout (if any)
        user    = the request
  └─> model returns one complete <screen> document
  └─> server renders it -> diagnostics
        errors or warnings? send them back as the next message, up to 2 automatic rounds
  └─> user sees the preview (and the boxes picture), says what to change, repeat
  └─> accept = the layout is saved as inkapps/<id>/layout.xml (versioned with the app)
```

- **Any model:** the server talks to the model through one small adapter (send
  messages, get text back). The default is a Claude Haiku-class model for cost, with
  the model and API key in settings. A local model behind an OpenAI-compatible
  endpoint would be another adapter.
- **Why a cheap model is enough:**
  - The language is small.
  - The skill file holds complete examples.
  - The engine does every calculation.
  - The diagnostics name the exact fix.

  A bigger model is only needed when a layout runs into the language's limits, at
  which point the answer is to extend the language.

### API (server)

| Endpoint | Purpose |
|---|---|
| `GET /api/layout/skill?display=<preset>` | The skill file, generated for that display |
| `POST /api/layout/render` `{layout, data, display}` | PNG, diagnostics and boxes. Works without any AI, for people writing layouts by hand too |
| `POST /api/layout/chat` `{app, message, history}` | One turn of the loop above, including the automatic fix rounds |

`/api/layout/render` is also what an outside tool or agent can call. Claude Code with
the skill file installed can design layouts against a running server the same way.

---

## 5. The skill file

The skill file is one Markdown file, generated from the code so it can never drift from
what the renderer accepts. It has front matter (`name`, `description`), so it also works
as an agent skill. It contains:

1. **What you are making:** the display's size and colours, orientation, the
   preset's notes ("red is slow to refresh: use it for one or two accents").
2. **Rules that matter most**, in a short list:
   - Never compute positions.
   - Use rows and columns.
   - Every text element gets a `fit`.
   - Use no more than three text sizes.
   - Red only for what needs attention.
3. **Element reference:** the tables in §2, generated from the renderer's element
   registry, with each attribute's allowed values.
4. **Fonts and their allowed sizes**, with how many characters of each size fit
   across this display.
5. **Icon list:** names and drawn sizes, generated from the icon set.
6. **Five complete examples with their `boxes` output:** a status card, a list, the
   pill grid, a big-number dashboard, and a message board.
7. **The answer format:** exactly one `<screen>` document in one fenced block, and
   nothing else.

---

## 6. Fonts

"Sharp everywhere" needs the same fonts everywhere, so the project ships them:

- **pixel:** a true bitmap-style font for 8–16 px (for example Terminus or Spleen,
  both freely licensed). Pixel-perfect by construction.
- **sans:** a hinted TTF with a good 1-bit rendering at 11–48 px (DejaVu Sans, freely
  licensed). Allowed sizes are picked by rendering each candidate size and checking it
  on a real panel once.
- **mono:** DejaVu Sans Mono, for IDs and numbers.

Licences are to be checked before anything is added to the repo. The current service
label keeps using system fonts (Tahoma/Consolas) until it is moved onto InkLayout.

---

## 7. Status (2026-11-12)

**Built** (`ShelfKit-Server/shelfkit/inklayout/`, tests in `tests/inklayout_test.py`):
- **L1:**
  - Parse and validation (DOCTYPE/entities refused, size and node caps)
  - `col`/`row`/`grid`/`stack`/`text`/`icon`/`bar`/`line`/`spacer`
  - `w`/`h` as px, %, `fill`, `fill:N`, `auto`; `padding`, `gap`, `align`, `justify`
  - `border`, `radius`, colours, and the `checker`/`dots`/`hatch` patterns
  - Text fit: `ellipsis`, `shrink` and `wrap`, with `lines`
  - Diagnostics and the boxes picture
- **L2 (most of it):**
  - `{{ }}` with filters, `a ? 'x' : 'y'`, comparisons, `and`/`or`/`not`
  - `if=` and `<repeat each as>` (with `loop.index`/`first`/`last`)
  - `InkApp(layout=...)` with `@app.data`
- **Behaviour the spec didn't state:**
  - In a `row`, children default to `align="center"`; in a `col`, to `stretch`.
  - A single text line that doesn't have room for a full line height is still drawn when its ink fits: digits in a tight, bordered cell. It is centred.
  - When a `row` is too wide, its auto-sized children give up width in proportion, and their text is then cut and reported.
- **Checked by a test:** the push pipeline (`preview.render` with threshold) changes no pixel of a rendered layout.
- **L3 (skill file):**
  - `shelfkit/inklayout/skill.py` builds the file from the renderer's own registry: elements and their attributes, sharp sizes, fonts, icons, the display preset's size and colours, a characters-per-line table measured with the real fonts, and five rendered examples (status card, to-do list, month grid, big number, message board) with their box pictures.
  - It is about 13 KB. A test checks that every element, attribute and icon is in the file and that every example renders with no error or warning.
  - Get it with `GET /api/layout/skill?display=<id>&orientation=<portrait|landscape>` or `python -m shelfkit.inklayout skill [--display ID] [--orientation landscape] [--out SKILL.md]`.
  - `python -m shelfkit.inklayout render layout.xml [--data d.json] [--out screen.png]` renders a layout and prints its diagnostics and boxes.

**Not yet:**
- `<image>`
- The `pixel` font, bundled fonts and per-font size lists. System fonts (Tahoma/Consolas/DejaVu) are used for now, so rendering can still differ between servers, and so can the skill file's characters-per-line table.
- L4: the model adapter and `/api/layout/chat`

**Skill-file rule learned in the playground:** don't put text on a pattern. It is unreadable on the panel. Use a solid background with a contrasting text colour.

## 8. Where it fits in the InkServices plan

A new chunk after chunk 1:

| Step | What you get |
|---|---|
| L1 | The layout engine: parse and validate, the box model (row/col/grid/stack, sizes, padding), text with fit rules, colours and patterns, diagnostics, boxes text. `python -m shelfkit.inklayout render layout.xml --data sample.json` |
| L2 | Data binding (paths, filters, `repeat`, `if`), icons, bar, image. `InkApp(layout="layout.xml")` with a `data(tag)` function instead of `render` |
| L3 | Bundled fonts and their allowed-size tables; the skill-file generator; `/api/layout/render` and `/api/layout/skill` |
| L4 | The model adapter and `/api/layout/chat` with automatic fix rounds; the Dev tab's Design pane uses it (replaces chunk 9's "AI layout chat") |
