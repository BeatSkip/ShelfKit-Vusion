"""The surface an app draws a tag's screen on.

Sized and coloured by the tag's display preset (shelfkit/displays.py). Text is
drawn the way the service label draws it - anti-aliasing off, hinted fonts at whole
pixel sizes - because the frame is thresholded to the panel's few colours and
anti-aliased text turns into ragged strokes there. Every text helper clips to the
canvas, so an app can never push a line off the edge by accident.

`canvas.image` (PIL RGB) and `canvas.draw` (ImageDraw) are there for anything the
helpers do not cover; stick to `canvas.colors` and it will come out as drawn.
"""

from __future__ import annotations

from PIL import Image, ImageDraw

from .. import displays
from ..service_image import _wrap, font


def _ink_right(text: str, f) -> int:
    """Where the ink ends when drawn with anti-aliasing off. Hinted 1-bit glyphs are
    wider than the default (anti-aliased) measurement says: Tahoma 14 'xxxxxxx…'
    measures 60 px but draws 67 px, so measure in mode '1', the way it is drawn."""
    if not text:
        return 0
    try:
        return int(f.getbbox(text, mode="1")[2])
    except TypeError:           # the built-in bitmap font takes no mode
        return int(f.getbbox(text)[2])


def _fits(text: str, f, limit: int) -> str:
    """Clip text so its *ink* ends within limit, with an ellipsis when shortened.

    service_image's version measures the anti-aliased advance width, which can be
    several pixels short of what 1-bit drawing produces (see _ink_right)."""
    if _ink_right(text, f) <= limit:
        return text
    while text and _ink_right(text + "…", f) > limit:
        text = text[:-1]
    return text + "…" if text else ""

BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (255, 0, 0)


class Canvas:
    def __init__(self, display: displays.DisplayPreset | None = None) -> None:
        self.display = display or displays.preset(displays.DEFAULT_PRESET)
        self.width, self.height = self.display.width, self.display.height
        self.colors = dict(self.display.colors)
        background = self.colors.get("white", WHITE)
        self.image = Image.new("RGB", (self.width, self.height), background)
        self.draw = ImageDraw.Draw(self.image)
        self.draw.fontmode = "1"            # no anti-aliasing: see the module docstring

    def _colour(self, color) -> tuple[int, int, int] | None:
        """An RGB the panel can show; names ('red') are looked up in the preset."""
        if color is None:
            return None
        rgb = self.colors.get(color) if isinstance(color, str) else tuple(color)
        if rgb is None or tuple(rgb) not in {tuple(c) for c in self.colors.values()}:
            raise ValueError(f"{self.display.name} cannot show colour {color!r}; "
                             f"it has {', '.join(self.colors)}")
        return tuple(rgb)

    def text(self, xy, s: str, size: int = 14, color=BLACK, bold: bool = False,
             mono: bool = False, max_width: int | None = None) -> int:
        """One line, cut with an ellipsis at max_width (default: the right edge).
        Returns the y just below it."""
        x, y = int(xy[0]), int(xy[1])
        f = font(size, mono=mono, bold=bold)
        limit = max(0, min(max_width if max_width is not None else self.width - x,
                           self.width - x))
        self.draw.text((x, y), _fits(str(s), f, limit), font=f, fill=self._colour(color))
        return y + self._line_height(f)

    def wrap(self, xy, s: str, size: int = 12, color=BLACK, bold: bool = False,
             max_width: int | None = None, max_lines: int = 3) -> int:
        """Word-wrapped text, at most max_lines (the last one ends in an ellipsis when
        cut). Returns the y just below the last line drawn."""
        x, y = int(xy[0]), int(xy[1])
        f = font(size, bold=bold)
        limit = max(0, min(max_width if max_width is not None else self.width - x,
                           self.width - x))
        fill = self._colour(color)
        step = self._line_height(f)
        for line in _wrap(str(s), f, limit, max(1, max_lines)):
            self.draw.text((x, y), _fits(line, f, limit), font=f, fill=fill)
            y += step
        return y

    def rect(self, box, fill=None, outline=BLACK, width: int = 1) -> None:
        self.draw.rectangle(box, fill=self._colour(fill), outline=self._colour(outline),
                            width=width)

    def line(self, points, color=BLACK, width: int = 1) -> None:
        self.draw.line(points, fill=self._colour(color), width=width)

    def paste(self, image: Image.Image, xy=(0, 0)) -> None:
        """Paste a picture as-is. It is reduced to the panel's colours on the way out,
        like any pushed image, so photos come out thresholded."""
        self.image.paste(image.convert("RGB"), (int(xy[0]), int(xy[1])))

    @staticmethod
    def _line_height(f) -> int:
        box = f.getbbox("Ag")
        return int(box[3] - min(0, box[1])) + 2
