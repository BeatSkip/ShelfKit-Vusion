"""The service label: a 152x296 frame that says what this tag is.

Modelled on the stock label the tags ship with (top/bottom orientation marks, the
ShelfKit banner, a serial, the black and red patches) but carrying what actually
matters now that tags are flashed and updated over the air:

* the **node id** in large type, so a tag in hand can be matched to a row in the
  Fleet screen without opening the Console,
* its **alias**, if it has one,
* a free-text **note** (a development note, a location, "do not use" ...),
* a black and a red patch, so a panel that has lost a colour is obvious.

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
FONT_DIRS = (Path(r"C:\Windows\Fonts"), Path("/usr/share/fonts/truetype/dejavu"))
MONO_FONTS = ("consola.ttf", "consolab.ttf", "DejaVuSansMono.ttf")
SANS_FONTS = ("arialbd.ttf", "ariblk.ttf", "arial.ttf", "DejaVuSans-Bold.ttf")


def _font(size: int, mono: bool = False) -> ImageFont.ImageFont:
    """A scalable font if one can be found, else Pillow's built-in one."""
    for name in MONO_FONTS if mono else SANS_FONTS:
        for folder in FONT_DIRS:
            path = folder / name
            if path.is_file():
                try:
                    return ImageFont.truetype(str(path), size)
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


def draw(node_id: int, alias: str | None = None, note: str | None = None,
         when: datetime | None = None) -> Image.Image:
    """The whole label as a panel-sized RGB image."""
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    draw = ImageDraw.Draw(image)
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BLACK, width=2)

    # orientation: which way is up on the shelf
    draw.text((WIDTH // 2, 8), "TOP", font=_font(13), fill=BLACK, anchor="ma")
    draw.polygon([(WIDTH // 2 - 8, 32), (WIDTH // 2 + 8, 32), (WIDTH // 2, 22)], fill=BLACK)

    # the banner
    draw.rectangle([MARGIN, 38, WIDTH - 1 - MARGIN, 62], fill=RED)
    draw.text((WIDTH // 2, 50), "ShelfKit", font=_font(19), fill=WHITE, anchor="mm")

    # the identity, which is what this label is really for
    draw.text((WIDTH // 2, 68), "WIRELESS ID", font=_font(10), fill=BLACK, anchor="ma")
    draw.text((WIDTH // 2, 82), f"{node_id:04X}", font=_font(40, mono=True), fill=BLACK,
              anchor="ma")

    width = WIDTH - 2 * MARGIN - 4
    y = 128
    alias_font = _font(15)
    if alias:
        draw.rectangle([MARGIN, y - 2, WIDTH - 1 - MARGIN, y + 18], outline=BLACK, width=1)
        draw.text((WIDTH // 2, y + 8), _fits(alias, alias_font, width), font=alias_font,
                  fill=BLACK, anchor="mm")
        y += 24

    note = (note or "").strip()
    if note:
        note_font = _font(11)
        for line in _wrap(note, note_font, width, 4):
            draw.text((MARGIN + 2, y), line, font=note_font, fill=BLACK)
            y += 14

    # colour patches: a panel that lost red is obvious next to these
    draw.rectangle([MARGIN + 6, 210, MARGIN + 36, 240], fill=BLACK)
    draw.rectangle([WIDTH - MARGIN - 36, 210, WIDTH - MARGIN - 6, 240], fill=RED)
    draw.text((WIDTH // 2, 224), "B/W/R", font=_font(9), fill=BLACK, anchor="mm")

    # when it was written, so a stale label is recognisable
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    draw.text((WIDTH // 2, 252), stamp, font=_font(9), fill=BLACK, anchor="ma")

    # orientation again, at the bottom
    draw.polygon([(WIDTH // 2 - 8, 274), (WIDTH // 2 + 8, 274), (WIDTH // 2, 284)],
                 outline=BLACK)
    draw.text((WIDTH // 2, 285), "bottom", font=_font(9), fill=BLACK, anchor="ma")
    return image


def write(path: Path, node_id: int, alias: str | None = None, note: str | None = None,
          when: datetime | None = None) -> Path:
    """Draw the label and save it; returns the path for the render pipeline."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    draw(node_id, alias, note, when).save(path, format="PNG")
    return path
