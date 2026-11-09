"""The service label: a 152x296 frame that says what this tag is.

Modelled on the stock label the tags ship with (top/bottom orientation marks, the
ShelfKit banner, the black and red patches) but carrying what matters now that tags
are flashed and updated over the air:

* the **node id** in large type, so a tag in hand can be matched to a row in the
  Fleet screen without opening the Console,
* its **alias** and a free-text **note**,
* the **firmware** it last reported (version and build) and its **battery**, when
  the server has heard them,
* a black and a red patch, so a panel that has lost a colour is obvious.

Text on a 1-bit panel: the label is thresholded, so anti-aliased text turns into
ragged, uneven strokes. Everything here is drawn with anti-aliasing off (fontmode
"1"), in fonts that are hinted for small pixel sizes (Tahoma, Consolas), at whole-pixel
sizes and positions, with Pillow's basic layout so glyph advances are whole pixels
too. Hinting snaps the stems to the pixel grid, which is what keeps 11-12 px text
legible.

Everything is drawn black/white/red and at panel size, so the render pipeline does
not have to scale or dither it: `App.service_image()` writes the PNG, renders it
with fit=stretch and dither=threshold, and pushes it like any other image.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 152, 296
MARGIN = 6
RED = (255, 0, 0)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
FONT_DIRS = (Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts/truetype/dejavu"),
             Path("/usr/share/fonts/TTF"))
MONO_FONTS = ("consolab.ttf", "consola.ttf", "DejaVuSansMono-Bold.ttf", "DejaVuSansMono.ttf")
SANS_FONTS = ("tahomabd.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
TEXT_FONTS = ("tahoma.ttf", "arial.ttf", "DejaVuSans.ttf")


def _font(size: int, mono: bool = False, bold: bool = True) -> ImageFont.ImageFont:
    """A hinted scalable font if one can be found, else Pillow's built-in one."""
    for name in MONO_FONTS if mono else SANS_FONTS if bold else TEXT_FONTS:
        for folder in FONT_DIRS:
            path = folder / name
            if path.is_file():
                try:    # BASIC layout: whole-pixel advances, no kerning blur
                    return ImageFont.truetype(str(path), size,
                                              layout_engine=ImageFont.Layout.BASIC)
                except OSError:
                    continue
    try:                        # Pillow >= 10.1 can scale the built-in font
        return ImageFont.load_default(size=size)
    except TypeError:           # older Pillow: the fixed bitmap font
        return ImageFont.load_default()


def _fits(text: str, font: ImageFont.ImageFont, limit: int) -> str:
    """Clip text to a width, with an ellipsis when it had to be shortened."""
    if font.getlength(text) <= limit:
        return text
    while text and font.getlength(text + "…") > limit:
        text = text[:-1]
    return text + "…"


def _wrap(text: str, font: ImageFont.ImageFont, limit: int, max_lines: int) -> list[str]:
    words, lines, current = text.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if font.getlength(candidate) <= limit:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = word
        if len(lines) == max_lines:
            break
    if current and len(lines) < max_lines:
        lines.append(current)
    if len(lines) == max_lines and font.getlength(" ".join(words)) > sum(
            font.getlength(line) + font.getlength(" ") for line in lines):
        lines[-1] = _fits(lines[-1] + " …", font, limit)
    return lines


def _centre(draw: ImageDraw.ImageDraw, y: int, text: str, font, fill=BLACK) -> None:
    """Text centred on the panel, on whole pixels, top edge at y."""
    x = (WIDTH - int(font.getlength(text))) // 2
    draw.text((x, y), text, font=font, fill=fill)


def _right(draw: ImageDraw.ImageDraw, y: int, text: str, font, right: int) -> int:
    """Text ending at x=right; returns the x it starts at."""
    x = right - int(font.getlength(text))
    draw.text((x, y), text, font=font, fill=BLACK)
    return x


def _battery(draw: ImageDraw.ImageDraw, x: int, y: int, percent: int) -> None:
    """A 22x10 battery symbol, filled in proportion to the charge (red when low)."""
    draw.rectangle([x, y, x + 19, y + 9], outline=BLACK, width=1)
    draw.rectangle([x + 20, y + 3, x + 21, y + 6], fill=BLACK)         # the terminal
    fill = max(0, min(100, percent)) * 16 // 100
    if fill:
        draw.rectangle([x + 2, y + 2, x + 1 + fill, y + 7],
                       fill=RED if percent < 20 else BLACK)


def draw(node_id: int, alias: str | None = None, note: str | None = None,
         when: datetime | None = None, fw: dict | None = None,
         battery: dict | None = None) -> Image.Image:
    """The whole label as a panel-sized RGB image.

    fw is the tag's last report ({"version", "build", ...}), battery is
    {"volts", "percent"}; either may be None when the server has not heard it.
    """
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.fontmode = "1"                 # no anti-aliasing: see the module docstring
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BLACK, width=2)

    small = _font(11, bold=False)
    label = _font(11)
    inner = WIDTH - 2 * MARGIN - 4
    left, right = MARGIN + 2, WIDTH - MARGIN - 2

    # orientation: which way is up on the shelf
    draw.polygon([(WIDTH // 2 - 7, 17), (WIDTH // 2 + 7, 17), (WIDTH // 2, 8)], fill=BLACK)
    _centre(draw, 19, "TOP", label)

    # the banner
    draw.rectangle([MARGIN, 36, WIDTH - 1 - MARGIN, 58], fill=RED)
    _centre(draw, 39, "ShelfKit", _font(16), WHITE)

    # the identity, which is what this label is really for
    _centre(draw, 64, "WIRELESS ID", small)
    _centre(draw, 78, f"{node_id:04X}", _font(40, mono=True))

    y = 126
    if alias:
        alias_font = _font(14)
        draw.rectangle([MARGIN, y, WIDTH - 1 - MARGIN, y + 20], outline=BLACK, width=1)
        _centre(draw, y + 3, _fits(alias, alias_font, inner), alias_font)
        y += 26

    note = (note or "").strip()
    if note:
        room = max(1, (168 - y) // 13)         # stay above the firmware rule
        for line in _wrap(note, small, inner, min(3, room)):
            draw.text((left, y), line, font=small, fill=BLACK)
            y += 13

    # what the tag runs and how full its battery is
    y = 172
    draw.line([MARGIN, y, WIDTH - 1 - MARGIN, y], fill=BLACK, width=1)
    y += 6
    draw.text((left, y), "FIRMWARE", font=small, fill=BLACK)
    _right(draw, y, f"{fw['version']}-{fw['build']}" if fw else "not reported", label, right)
    y += 18
    draw.text((left, y), "BATTERY", font=small, fill=BLACK)
    if battery:
        start = _right(draw, y, f"{battery['volts']:.2f} V", label, right)
        _battery(draw, start - 28, y + 1, battery["percent"])
        y += 15
        draw.text((left, y), f"about {battery['percent']}% left", font=small, fill=BLACK)
    else:
        _right(draw, y, "not reported", label, right)

    # colour patches: a panel that lost red is obvious next to these
    y = 236
    draw.line([MARGIN, y - 5, WIDTH - 1 - MARGIN, y - 5], fill=BLACK, width=1)
    draw.rectangle([left, y, left + 23, y + 17], fill=BLACK)
    draw.rectangle([left + 26, y, left + 49, y + 17], outline=BLACK, width=1)
    draw.rectangle([left + 52, y, left + 75, y + 17], fill=RED)
    draw.text((left + 82, y + 3), "B/W/R", font=small, fill=BLACK)

    # when it was written, so a stale label is recognisable
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    _centre(draw, 264, stamp, small)

    # orientation again, at the bottom
    draw.polygon([(WIDTH // 2 - 7, 282), (WIDTH // 2 + 7, 282), (WIDTH // 2, 290)],
                 fill=BLACK)
    return image


def write(path: Path, node_id: int, alias: str | None = None, note: str | None = None,
          when: datetime | None = None, fw: dict | None = None,
          battery: dict | None = None) -> Path:
    """Draw the label and save it; returns the path for the render pipeline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw(node_id, alias, note, when, fw, battery).save(path, format="PNG")
    return path
