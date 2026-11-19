"""App sprites for <image src="...">: small pictures from the app's own folder.

Two kinds of file, both reduced to the panel's own colours so what you see is what the
glass shows:

* ``name.png``: any PNG. Transparent pixels (alpha < 128) stay transparent; every other
  pixel becomes the nearest colour the display has (black, white, red).
* ``name.sprite``: pixel art as text, one character per pixel, so a model (or you) can
  write it like code::

      ; a bin, 8x8          <- lines starting with ';' are comments
      ..####..
      ########
      .#.##.#.
      .#.##.#.
      .######.

  ``#`` or ``k`` black, ``r`` red, ``w`` white, ``.`` or a space transparent. Rows may
  differ in length; short ones are padded with transparent.

A sprite is only ever scaled by a whole factor (``scale="2"``), so it stays sharp.
"""

from __future__ import annotations

import io
import re
from pathlib import Path

from PIL import Image

NAME = re.compile(r"^[A-Za-z0-9_-][A-Za-z0-9_.-]{0,60}\.(png|sprite)$")
MAX_BYTES = 256_000
MAX_SIDE = 296                     # before scaling: the panel's long side
SPRITE_INK = {"#": "black", "k": "black", "r": "red", "w": "white"}
SPRITE_CLEAR = {".", " "}


class SpriteError(ValueError):
    """What is wrong with a sprite, in words for the layout's diagnostics."""


class Assets:
    """Where <image src> files come from: an app's folder, plus files not saved yet
    (a proposal or the editor's unsaved text), which win over the folder."""

    def __init__(self, folder: str | Path | None = None,
                 files: dict[str, str | bytes] | None = None) -> None:
        self.folder = Path(folder) if folder else None
        self.files = dict(files or {})

    def read(self, name: str) -> bytes | None:
        if name in self.files:
            value = self.files[name]
            return value.encode("utf-8") if isinstance(value, str) else value
        if self.folder is None:
            return None
        path = self.folder / name
        try:
            if path.is_file() and path.stat().st_size <= MAX_BYTES:
                return path.read_bytes()
        except OSError:
            return None
        return None

    def names(self) -> list[str]:
        out = {n for n in self.files if NAME.match(n)}
        if self.folder is not None and self.folder.is_dir():
            out |= {p.name for p in self.folder.iterdir() if p.is_file() and NAME.match(p.name)}
        return sorted(out)


def _nearest(rgb, palette: dict[str, tuple]) -> tuple:
    return min(palette.values(), key=lambda c: sum((a - b) ** 2 for a, b in zip(rgb, c)))


def parse_sprite(text: str, palette: dict[str, tuple]) -> Image.Image:
    """A .sprite file as an RGBA image in the display's colours."""
    rows = [r.rstrip("\r") for r in text.splitlines() if not r.lstrip().startswith(";")]
    while rows and not rows[0].strip():
        rows.pop(0)
    while rows and not rows[-1].strip():
        rows.pop()
    if not rows:
        raise SpriteError("the sprite has no pixels")
    width = max(len(r) for r in rows)
    if width > MAX_SIDE or len(rows) > MAX_SIDE:
        raise SpriteError(f"the sprite is {width}x{len(rows)}; at most {MAX_SIDE} on a side")
    img = Image.new("RGBA", (width, len(rows)), (0, 0, 0, 0))
    px = img.load()
    for y, row in enumerate(rows):
        for x, ch in enumerate(row):
            if ch in SPRITE_CLEAR:
                continue
            colour = SPRITE_INK.get(ch.lower() if ch != "#" else ch)
            if colour is None:
                raise SpriteError(f"row {y + 1}, column {x + 1}: {ch!r} is not a pixel; "
                                  "use # (black), r (red), w (white) or . (nothing)")
            rgb = palette.get(colour)
            if rgb is None:
                raise SpriteError(f"this display has no {colour}")
            px[x, y] = (*rgb, 255)
    return img


def parse_png(data: bytes, palette: dict[str, tuple]) -> Image.Image:
    """A PNG as an RGBA image in the display's colours (alpha is either 0 or 255)."""
    try:
        with Image.open(io.BytesIO(data)) as opened:
            src = opened.convert("RGBA")
    except Exception as exc:  # noqa: BLE001 - any decoding problem is the file's
        raise SpriteError(f"not a PNG this server can read ({exc})") from None
    if src.width > MAX_SIDE or src.height > MAX_SIDE:
        raise SpriteError(f"the picture is {src.width}x{src.height}; at most {MAX_SIDE} on a "
                          "side (scale it up with scale=\"2\" instead)")
    out = Image.new("RGBA", src.size, (0, 0, 0, 0))
    sp, op = src.load(), out.load()
    cache: dict[tuple, tuple] = {}
    for y in range(src.height):
        for x in range(src.width):
            r, g, b, a = sp[x, y]
            if a < 128:
                continue
            rgb = cache.get((r, g, b))
            if rgb is None:
                rgb = cache[(r, g, b)] = tuple(_nearest((r, g, b), palette))
            op[x, y] = (*rgb, 255)
    return out


def load(assets: Assets | None, name: str, palette: dict[str, tuple]) -> Image.Image:
    """The sprite `name` from `assets`, in the display's colours. Raises SpriteError."""
    if not NAME.match(name or ""):
        raise SpriteError(f"src=\"{name}\": a .png or .sprite file name in the app's folder "
                          "(letters, digits, - _ . and no folders)")
    if assets is None:
        raise SpriteError("<image> needs an app: its files are looked up in the app's folder")
    data = assets.read(name)
    if data is None:
        have = assets.names()
        raise SpriteError(f"no file {name!r} in the app's folder"
                          + (f"; it has {', '.join(have)}" if have else
                             "; add a .png or a .sprite file next to layout.xml"))
    if name.endswith(".sprite"):
        return parse_sprite(data.decode("utf-8", errors="replace"), palette)
    return parse_png(data, palette)
