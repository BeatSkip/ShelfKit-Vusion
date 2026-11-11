#!/usr/bin/env python3
"""Tests for InkLayout, the screen description language (Documentation/InkLayout.md).

    python ShelfKit-Server/tests/inklayout_test.py

Same style as smoke.py: no pytest, exit code 0 = everything passed.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shelfkit.inklayout import render  # noqa: E402

FAILED: list[str] = []
PALETTE = {(0, 0, 0), (255, 255, 255), (255, 0, 0)}


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


def colours(img) -> set:
    return {c for _, c in img.getcolors(1 << 20)}


def msgs(result, level=None) -> str:
    return " | ".join(d["msg"] for d in result.diagnostics
                      if level is None or d["level"] == level)


def box(result, path):
    return next((b for b in result.layout if b["path"] == path), None)


def test_basics() -> None:
    print("basics")
    r = render('<screen><text size="16" bold="true">Hello</text></screen>')
    check("renders ok", r.ok, msgs(r))
    check("panel size", r.image.size == (152, 296))
    check("only panel colours", colours(r.image) <= PALETTE, colours(r.image))
    check("text was drawn", (0, 0, 0) in colours(r.image))
    check("boxes text describes it", "text" in r.boxes and "Hello" in r.boxes, r.boxes)

    r = render('<screen orientation="landscape"><text>Wide</text></screen>')
    check("landscape swaps the size", r.image.size == (296, 152))

    r = render('<screen bg="red"><text color="white">On red</text></screen>')
    check("named colours", colours(r.image) == {(255, 0, 0), (255, 255, 255)}, colours(r.image))


def test_errors() -> None:
    print("errors are explained, never crash")
    r = render("<screen><txt>typo</txt></screen>")
    check("unknown element is an error", not r.ok and "txt" in msgs(r, "error")
          and "text" in msgs(r, "error"), msgs(r))
    r = render('<screen><text colour="red">x</text></screen>')
    check("unknown attribute is a warning", r.ok and "colour" in msgs(r, "warn"), msgs(r))
    r = render('<screen><text color="orange">x</text></screen>')
    check("colour the panel lacks", not r.ok and "orange" in msgs(r, "error")
          and "red" in msgs(r, "error"), msgs(r))
    r = render("<screen><text>unclosed</screen>")
    check("broken XML is an error, not an exception", not r.ok and r.image is not None, msgs(r))
    r = render('<!DOCTYPE x [<!ENTITY a "b">]><screen><text>&a;</text></screen>')
    check("DOCTYPE / entities refused", not r.ok and "DOCTYPE" in msgs(r, "error"), msgs(r))
    r = render("<col><text>x</text></col>")
    check("root must be <screen>", not r.ok and "screen" in msgs(r, "error"), msgs(r))
    r = render('<screen><text size="15">x</text></screen>')
    check("size snaps to an allowed one, with a note",
          r.ok and "15" in msgs(r, "info") and "14" in msgs(r, "info"), msgs(r))


def test_text_fit() -> None:
    print("text never leaves its box")
    long = "Wednesday the twelfth of November"
    r = render(f'<screen padding="4"><text size="16" bold="true">{long}</text></screen>')
    check("cut text is reported with numbers",
          "cut" in msgs(r, "warn") and "px" in msgs(r, "warn"), msgs(r))
    check("cut text ends in an ellipsis", "…" in r.boxes, r.boxes)
    right = r.image.crop((152 - 4, 0, 152, 296))
    check("nothing drawn in the right padding", colours(right) == {(255, 255, 255)})

    r = render(f'<screen padding="4"><text size="24" fit="shrink">{long[:20]}</text></screen>')
    check("shrink picks a smaller size", "shrink" in msgs(r, "info") or r.ok, msgs(r))
    b = box(r, "screen/text[1]")
    check("shrunk text fits without a cut", b and "…" not in b["text"] and b["size"] < 24, b)

    r = render('<screen padding="0"><stack w="18" h="15" border="2 red">'
               '<text size="10" align="center">12</text></stack></screen>')
    b = box(r, "screen/stack[1]/text[1]")
    check("a single line fits by its ink in a tight cell", r.ok and b and b["text"] == "12"
          and not msgs(r, "warn"), (b, msgs(r)))

    r = render(f'<screen padding="4"><text size="14" lines="2">{long} {long}</text></screen>')
    b = box(r, "screen/text[1]")
    check("lines=2 wraps onto two lines", b and b["lines"] == 2, b)


def test_layout() -> None:
    print("layout engine")
    r = render('<screen padding="0" gap="0">'
               '<col h="fill"/><col h="fill:2"/><col h="100"/></screen>')
    a, b, c = (box(r, f"screen/col[{i}]") for i in (1, 2, 3))
    check("fill shares the rest by weight", a and b and c and c["h"] == 100
          and a["h"] + b["h"] == 196 and abs(b["h"] - 2 * a["h"]) <= 1, (a, b, c))
    check("whole pixels everywhere", all(isinstance(x[k], int) for x in r.layout
                                         for k in ("x", "y", "w", "h")))

    r = render('<screen padding="4"><row justify="between">'
               '<text>Left</text><text>Right</text></row></screen>')
    left, rt = box(r, "screen/row[1]/text[1]"), box(r, "screen/row[1]/text[2]")
    check("justify=between pushes to the edges", left and rt and left["x"] == 4
          and rt["x"] + rt["w"] == 148, (left, rt))

    r = render('<screen padding="2"><grid cols="7" gap="2">'
               + "<col h='10' bg='black'/>" * 14 + "</grid></screen>")
    cells = [b for b in r.layout if b["path"].startswith("screen/grid[1]/col")]
    check("grid makes equal cells", len(cells) == 14 and len({c["w"] for c in cells}) == 1
          and cells[7]["y"] > cells[0]["y"], [(c["x"], c["y"], c["w"]) for c in cells[:8]])

    r = render('<screen padding="0"><col h="40"><col h="30"/><col h="30"/></col></screen>')
    check("overflow is reported", "need" in msgs(r, "warn"), msgs(r))

    r = render('<screen><row><icon name="pill" size="24"/><text>Taken</text></row></screen>')
    check("icon renders", r.ok and box(r, "screen/row[1]/icon[1]")["w"] == 24, msgs(r))
    r = render('<screen><icon name="unicorn"/></screen>')
    check("unknown icon is reported with the list", "unicorn" in msgs(r) and "pill" in msgs(r),
          msgs(r))
    r = render('<screen><bar value="3" max="4" h="10" border="1 black"/></screen>')
    check("bar renders", r.ok and (0, 0, 0) in colours(r.image), msgs(r))


def test_patterns() -> None:
    print("patterns instead of grey")
    r = render('<screen padding="0"><col h="20" bg="checker"/></screen>')
    px = [r.image.getpixel((x, 5)) for x in range(4)]
    check("checker alternates pixels", px[0] != px[1] and px[0] == px[2], px)
    check("patterns stay in the palette", colours(r.image) <= PALETTE)
    r = render('<screen padding="0"><col h="20" bg="hatch red"/></screen>')
    check("coloured pattern", (255, 0, 0) in colours(r.image))


def test_data() -> None:
    print("data binding")
    data = {"name": "Kitchen", "n": 3,
            "days": [{"d": 1, "taken": True}, {"d": 2, "taken": False}, {"d": 3, "taken": True}],
            "note": ""}
    src = """<screen>
      <text>{{ data.name | upper }}: {{ data.n }}</text>
      <grid cols="7"><repeat each="data.days" as="day">
        <col h="10" bg="{{ day.taken ? 'black' : 'white' }}" border="1 black"/>
      </repeat></grid>
      <text if="data.note">{{ data.note }}</text>
      <text>{{ data.nope | default:"-" }}</text>
      <text>{{ data.missing }}</text>
    </screen>"""
    r = render(src, data=data)
    check("interpolation and filters", "KITCHEN: 3" in r.boxes, r.boxes)
    cells = [b for b in r.layout if b["path"].startswith("screen/grid[1]/col")]
    check("repeat makes one element per item", len(cells) == 3, len(cells))
    check("if= false drops the element", not any("text[2]" in b["path"] and b.get("text") == ""
                                                for b in r.layout) and r.boxes.count("text") == 3,
          r.boxes)
    check("default filter", "'-'" in r.boxes, r.boxes)
    check("missing path is reported", "data.missing" in msgs(r, "warn"), msgs(r))

    r = render('<screen><text>{{ tag.alias }} {{ now | time:"%H" }}</text></screen>',
               tag={"hex_id": "0101", "alias": "Shelf"})
    check("tag and now in context", "Shelf" in r.boxes, r.boxes)
    r = render('<screen><text>{{ data.n + 1 }}</text></screen>', data={"n": 1})
    check("bad expression is reported", not r.ok and "data.n + 1" in msgs(r, "error"), msgs(r))


def test_matches_panel() -> None:
    print("preview is exactly what the tag shows")
    from shelfkit import preview
    src = """<screen padding="4" gap="4">
      <row bg="black" padding="3"><text color="white" bold="true" size="16">KITCHEN</text></row>
      <text size="48" bold="true" color="red" align="center">12</text>
      <col h="20" bg="checker"/>
      <bar value="2" max="3" h="8" border="1 black"/>
      <row gap="4"><icon name="pill"/><text size="12" fit="shrink">Last taken 08:02</text></row>
    </screen>"""
    r = render(src)
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "s.png"
        r.image.save(path)
        rendered = preview.render(path, "stretch", "threshold")
        back = preview.planes_to_image(rendered.bw, rendered.red).convert("RGB")
    a, b = r.image.tobytes(), back.tobytes()
    diff = sum(1 for i in range(0, len(a), 3) if a[i:i + 3] != b[i:i + 3])
    check("the push pipeline changes no pixel", diff == 0, f"{diff} pixels differ")


def test_skill() -> None:
    print("skill file")
    from shelfkit.inklayout import ELEMENTS, icons, skill
    md = skill.skill_markdown()
    check("has skill front matter", md.startswith("---\nname: ") and "description:" in md[:400])
    check("names the display and its size", "152 x 296" in md and "black" in md and "red" in md)
    check("lists every element", all(f"<{e}>" in md for e in ELEMENTS),
          [e for e in ELEMENTS if f"<{e}>" not in md])
    check("lists every icon", all(n in md for n in icons.names()))
    check("lists the sharp sizes", "10, 11, 12" in md)
    check("says how much text fits", "characters" in md)
    check("warns against text on patterns", "pattern" in md and "text on" in md.lower())
    check("stays small enough for a cheap model's prompt", len(md) < 30000, len(md))
    for ex in skill.EXAMPLES:
        r = render(ex["layout"], ex["data"], tag=skill.SAMPLE_TAG)
        noisy = [d for d in r.diagnostics if d["level"] in ("error", "warn")]
        check(f"example '{ex['title']}' renders cleanly", r.ok and not noisy, noisy)
        check(f"example '{ex['title']}' is in the file with its boxes",
              ex["layout"].strip() in md and r.boxes.splitlines()[1] in md)
    landscape = skill.skill_markdown(orientation="landscape")
    check("landscape variant", "296 x 152" in landscape)


def main() -> int:
    for test in (test_basics, test_errors, test_text_fit, test_layout, test_patterns,
                 test_data, test_matches_panel, test_skill):
        try:
            test()
        except Exception as exc:  # noqa: BLE001 - report and keep going
            import traceback
            traceback.print_exc()
            check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
