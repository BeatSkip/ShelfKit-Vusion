# InkLayout, the screen language

The full spec is in `Documentation/InkLayout.md`, and the engine is `ShelfKit-Server/shelfkit/inklayout/`. The authoritative, always-current element and attribute reference is the **generated skill file**: `GET /api/layout/skill?display=vusion-2.6-bwr&orientation=portrait`, or `python -m shelfkit.inklayout skill`. It is generated from the renderer's registry, so it can't drift from the code.

## Why it exists (relevant to UI design)

- **Made for cheap AI models and for people.** You describe structure (rows, columns, grids), never pixel positions. The engine does all the arithmetic.
- **Always sharp:**
  - whole pixels only
  - only the panel's colours
  - text drawn 1-bit, with a fit rule on every text element
  - grey only as `checker`/`dots`/`hatch` patterns
- **Data, not code.** It is safe to render AI-written layouts without a safety review.
- **The renderer answers in words.** Every render returns:
  - `diagnostics`: a list of `{level: error|warn|info, at: "screen/col[1]/text[2]", msg}`. Each message names the fix, e.g. "text cut to '…' (needs 131 px, box is 96 px). Use fit="shrink"…".
  - `boxes`: a text picture of every element's resolved size and position, so a model without vision can read it.
- **A layout with errors is never pushed to a tag.**

## The language, briefly

```xml
<screen padding="6" gap="6">                       <!-- display/orientation optional -->
  <row bg="black" padding="4 6" radius="3">
    <text color="white" bold="true" size="16">{{ tag.alias }}</text>
  </row>
  <text size="64" bold="true" color="red" fit="shrink">{{ data.n }}</text>
  <grid cols="7" gap="2">
    <repeat each="data.days" as="d">
      <col h="16" bg="{{ d.taken ? 'black' : 'white' }}" border="1 black"/>
    </repeat>
  </grid>
  <text if="data.message" fit="wrap" lines="4">{{ data.message }}</text>
  <spacer h="fill"/>
  <text size="11" align="center">{{ now | date:"%a %d %b" }}</text>
</screen>
```

- **Containers:** `col`, `row`, `grid` (cols, cell-h), `stack`.
- **Content:** `text`, `icon`, `bar`, `line`, `spacer`. `image` is specified but not built yet.
- **Sizes:** px, `%`, `fill`, `fill:N` or `auto`. Also `padding`, `gap`, `align`, `justify`, `bg`, `border`, `radius`, `if=`.
- **Bindings:** `{{ path | filter }}` over `tag.*`, `data.*`, `now`. Filters: `upper`, `lower`, `time`, `date`, `round`, `default`, `count`. Supports `a ? 'x' : 'y'`, comparisons and `and/or/not`, plus `<repeat each as>` with `loop.index/first/last`.
- **Icons** (pixel-drawn, whole-factor scaling): battery, bell, calendar, check, clock, cloud, cross, heart, home, message, moon, pill, rain, sun, warning.
- **Display presets:** only `vusion-2.6-bwr` (152×296, black/white/red) so far. `GET /api/layout/displays` lists them.

## Status

Built:
- L1: the engine, diagnostics and boxes
- Most of L2: bindings, repeat, if, icons, bar
- L3: the skill file

Not built:
- `<image>`
- Bundled fonts (system Tahoma/Consolas/DejaVu are used, so output can differ between machines)
- **L4, the AI chat loop:** a model adapter and `POST /api/layout/chat` with automatic fix rounds. Its UI was meant to be the Dev tab's Design pane.

## The planned AI loop (InkLayout §4)

1. The user describes the screen.
2. The server sends the skill file, the app's data shape with sample values, the current layout and the request to a cheap model.
3. The model returns one `<screen>`.
4. The server renders it. Any errors or warnings go back to the model automatically, for up to 2 rounds.
5. The user sees the preview and the boxes, and iterates.
6. Accepting saves `inkapps/<id>/layout.xml`.
