"""InkLayout pictures: the built-in icons and <image src> app sprites (.sprite and .png).

    python tests/sprites_test.py
"""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image  # noqa: E402

from shelfkit import inklayout  # noqa: E402
from shelfkit.inklayout import icons, sprites  # noqa: E402
from shelfkit.inklayout.skill import skill_markdown  # noqa: E402
from shelfkit.inkservices.screen import draw_screen  # noqa: E402
from shelfkit.inkservices.sdk import InkApp, TagContext  # noqa: E402
from shelfkit import displays  # noqa: E402

FAILED: list[str] = []
BLACK, WHITE, RED = (0, 0, 0), (255, 255, 255), (255, 0, 0)


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


BIN = """; a bin
..##..
######
.#rr#.
.#..#.
"""


def render(layout: str, files=None, folder=None):
    return inklayout.render(layout, {}, assets=sprites.Assets(folder, files)
                            if (files is not None or folder is not None) else None)


def main() -> int:
    # ── icons ──
    check("at least 50 built-in icons", len(icons.names()) >= 50, len(icons.names()))
    for name in ("snow", "bolt", "trash", "up", "car", "gear", "wifi", "lock"):
        check(f"icon {name} exists", name in icons.ICONS)
    r = inklayout.render('<screen><icon name="trash" size="24"/></screen>', {})
    check("a new icon draws without problems", r.ok and not r.diagnostics, r.diagnostics)
    md = skill_markdown()
    check("the skill file lists the new icons and <image>", "trash" in md and "<image>" in md
          and ".sprite" in md)

    # ── .sprite ──
    r = render('<screen padding="0" align="start"><image src="bin.sprite" scale="2"/></screen>',
               {"bin.sprite": BIN})
    px = r.image.load()
    check("a .sprite draws", r.ok, r.diagnostics)
    check("its pixels land where drawn, scaled 2x",
          px[0, 0] == WHITE and px[4, 0] == BLACK and px[5, 1] == BLACK
          and px[4, 4] == RED and px[6, 5] == RED and px[0, 2] == BLACK, [px[4, 0], px[4, 4]])
    check("transparent pixels keep what is behind", px[4, 6] == WHITE and px[2, 6] == BLACK)
    check("its box is the scaled size", "image 12x8" in r.boxes, r.boxes)

    r = render('<screen padding="0" bg="black" align="start">'
               '<image src="bin.sprite" color="white"/></screen>', {"bin.sprite": BIN})
    px = r.image.load()
    check("color= recolours the ink", px[2, 0] == WHITE and px[2, 2] == WHITE
          and px[0, 0] == BLACK, [px[2, 0], px[2, 2], px[0, 0]])

    r = render('<screen><image src="x.sprite"/></screen>', {"x.sprite": "..#..\n.#z#.\n"})
    check("a bad pixel character is an error that says where",
          not r.ok and any("row 2, column 3" in d["msg"] for d in r.diagnostics), r.diagnostics)

    r = render('<screen><image src="none.sprite"/></screen>', {"bin.sprite": BIN})
    check("a missing file is an error that lists what is there",
          not r.ok and any("bin.sprite" in d["msg"] for d in r.diagnostics), r.diagnostics)
    r = inklayout.render('<screen><image src="bin.sprite"/></screen>', {})
    check("without an app there is nothing to load from", not r.ok, r.diagnostics)
    for bad in ("../secret.png", "sub/x.png", "x.gif", ""):
        r = render(f'<screen><image src="{bad}"/></screen>', {})
        check(f"src {bad!r} is refused", not r.ok, r.diagnostics)

    r = render('<screen padding="0"><row h="10"><image src="bin.sprite" scale="4"/></row></screen>',
               {"bin.sprite": BIN})
    check("a picture bigger than its box warns that it is cut",
          any("is cut" in d["msg"] for d in r.diagnostics), r.diagnostics)

    # ── .png, from a folder ──
    folder = Path(tempfile.mkdtemp())
    img = Image.new("RGBA", (4, 2), (0, 0, 0, 0))
    img.putpixel((0, 0), (30, 30, 30, 255))      # dark grey -> black
    img.putpixel((1, 0), (230, 40, 50, 255))     # a red -> red
    img.putpixel((2, 0), (240, 240, 240, 255))   # near white -> white
    img.putpixel((3, 0), (0, 0, 0, 40))          # mostly transparent -> nothing
    img.save(folder / "dot.png")
    r = render('<screen padding="0" bg="red" align="start"><image src="dot.png"/></screen>',
               folder=folder)
    px = r.image.load()
    check("a .png is reduced to the panel's colours",
          r.ok and px[0, 0] == BLACK and px[1, 0] == RED and px[2, 0] == WHITE
          and px[3, 0] == RED, [px[i, 0] for i in range(4)])
    big = Image.new("RGB", (400, 10), "white")
    buf = io.BytesIO()
    big.save(buf, format="PNG")
    r = render('<screen><image src="big.png"/></screen>', {"big.png": buf.getvalue()})
    check("a picture larger than the panel is refused", not r.ok, r.diagnostics)

    # ── through an app: unsaved files win over the folder ──
    (folder / "bin.sprite").write_text("##\n##\n", encoding="utf-8")
    r = render('<screen padding="0" align="start"><image src="bin.sprite"/></screen>',
               {"bin.sprite": "r\n"}, folder=folder)
    check("an unsaved sprite wins over the saved one", r.image.load()[0, 0] == RED
          and "image 1x1" in r.boxes, r.boxes)

    (folder / "layout.xml").write_text(
        '<screen padding="0" align="start"><image src="bin.sprite" scale="3"/></screen>',
        encoding="utf-8")
    app = InkApp("pic", layout="layout.xml")
    app.folder = folder
    tag = TagContext(hex_id="0101", alias=None, notes=None, config={}, data={}, shared={},
                     db=None, battery=None, display=displays.preset(None))
    image, result = draw_screen(app, tag)
    check("an app's layout finds sprites in its folder", result.ok
          and image.getpixel((5, 5)) == BLACK and image.getpixel((6, 0)) == WHITE,
          result.diagnostics)

    print("\nALL PASS" if not FAILED else f"\nFAILED: {', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
