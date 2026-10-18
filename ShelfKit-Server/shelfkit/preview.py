"""Server-side rendering for the editor previews and the image push.

One place decides what an image looks like on the panel, so the preview and the
bytes sent to the tag can never disagree:

    load -> rotate upright -> fit 152x296 -> quantise to black/white/red

`render()` returns the two transport planes *and* PNGs of the same frame: the
colour "original" (after fit) and the 1:1 "on device" image. The browser never
dithers anything - spec rule - it just displays these PNGs with
`image-rendering: pixelated`.

The panel is a three-colour BWR part, so "on device" is black/white/red rather
than 1-bit mono: a mono preview would hide exactly the mistake it exists to
catch (a red pixel landing where ink should be).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from PIL import Image

from . import png2epd

PANEL_W, PANEL_H = png2epd.PANEL_W, png2epd.PANEL_H   # 152 x 296, portrait
FIT_MODES = ("cover", "contain", "stretch")
DITHERS = ("threshold", "floyd-steinberg", "bayer4")
DEFAULT_FIT = "cover"
# Threshold is the default rather than the spec's Floyd-Steinberg: this panel is
# three-colour, and error diffusion across a logo scatters red speckle into the
# white. Pictures look better with dithering, line art does not - hence a choice.
DEFAULT_DITHER = "threshold"
MIDTONE_WARN = 0.40          # >40% midtone pixels: dithering will look muddy
_BAYER4 = ((0, 8, 2, 10), (12, 4, 14, 6), (3, 11, 1, 9), (15, 7, 13, 5))
_CACHE: "OrderedDict[str, Render]" = OrderedDict()
_CACHE_MAX = 16


@dataclass
class Render:
    key: str
    angle: int
    source: tuple[int, int]
    fitted: tuple[int, int]
    midtone: float
    bw: bytes
    red: bytes
    original_png: bytes
    device_png: bytes

    @property
    def size(self) -> tuple[int, int]:
        return PANEL_W, PANEL_H


def _composite_over_white(img: Image.Image) -> Image.Image:
    """Flatten transparency onto a white substrate, as the panel shows it."""
    if img.mode in ("RGBA", "LA"):
        canvas = Image.new("RGBA", img.size, "white")
        canvas.alpha_composite(img.convert("RGBA"))
        return canvas
    return img.convert("RGBA")


def _upright(img: Image.Image) -> tuple[Image.Image, int]:
    """Rotate so the artwork reads upright when the panel is mounted portrait.

    The panel is driven 152 wide x 296 tall; a landscape source would arrive
    sideways, so it gets the long-standing 90 degree turn.
    """
    if img.width > img.height:
        return img.rotate(-90, expand=True), 90
    return img, 0


def _fit(img: Image.Image, mode: str) -> Image.Image:
    """Scale and place the source into the panel's footprint.

    cover crops the overflow (the image is bigger than the panel, so it cannot be
    pasted at a negative offset - it is cropped), contain centres it on white.
    """
    if mode not in FIT_MODES:
        mode = DEFAULT_FIT
    if img.mode != "RGBA":
        img = img.convert("RGBA")       # alpha_composite needs RGBA on both sides
    if img.size == (PANEL_W, PANEL_H):
        return img
    if mode == "stretch":
        return img.resize((PANEL_W, PANEL_H), Image.LANCZOS)

    scale = (max if mode == "cover" else min)(PANEL_W / img.width, PANEL_H / img.height)
    resized = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS
    )
    if resized.width >= PANEL_W and resized.height >= PANEL_H:
        left = (resized.width - PANEL_W) // 2
        top = (resized.height - PANEL_H) // 2
        return resized.crop((left, top, left + PANEL_W, top + PANEL_H))

    canvas = Image.new("RGBA", (PANEL_W, PANEL_H), "white")
    canvas.alpha_composite(
        resized, ((PANEL_W - resized.width) // 2, (PANEL_H - resized.height) // 2)
    )
    return canvas


def _midtone_ratio(img: Image.Image) -> float:
    """Fraction of pixels that are neither clearly ink nor clearly white."""
    px = img.load()
    mid = 0
    total = img.width * img.height
    for y in range(img.height):
        for x in range(img.width):
            r, g, b, _a = px[x, y]
            if r > 110 and r > g + 40 and r > b + 40:
                continue                      # red ink is not a midtone
            lum = (3 * r + 6 * g + b) // 10
            if 60 <= lum <= 190:
                mid += 1
    return round(mid / total, 3) if total else 0.0


def _planes_bayer(img: Image.Image) -> tuple[bytearray, bytearray]:
    """Ordered 4x4 dither: nudge each pixel by the matrix, then classify."""
    w, h = img.size
    bw = bytearray(b"\xff" * (w * h // 8))
    red = bytearray(b"\xff" * (w * h // 8))
    px = img.load()
    for y in range(h):
        row = _BAYER4[y & 3]
        for x in range(w):
            r, g, b, _a = px[x, y]
            if r > 110 and r > g + 40 and r > b + 40:
                kind = "red"
            else:
                nudge = (row[x & 3] + 0.5) * 4.0 - 32.0     # -32 .. +32
                lum = (3 * r + 6 * g + b) // 10 + nudge
                kind = "black" if lum < 128 else "white"
            if kind == "white":
                continue
            index = (y * w + x) >> 3
            mask = 0x80 >> (x & 7)
            if kind == "red":
                red[index] &= ~mask & 0xFF
            else:
                bw[index] &= ~mask & 0xFF
    return bw, red


def planes_to_image(bw, red) -> Image.Image:
    """The transport planes back as black/white/red pixels - the on-glass frame."""
    img = Image.new("RGB", (PANEL_W, PANEL_H), "white")
    px = img.load()
    for y in range(PANEL_H):
        for x in range(PANEL_W):
            index = (y * PANEL_W + x) >> 3
            mask = 0x80 >> (x & 7)
            if not bw[index] & mask:
                px[x, y] = (0, 0, 0)
            elif not red[index] & mask:
                px[x, y] = (255, 0, 0)
    return img


def _png(img: Image.Image) -> bytes:
    out = BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()


def render(path: str | Path, fit: str = DEFAULT_FIT, dither: str = DEFAULT_DITHER) -> Render:
    """Render one image for the panel, cached on (file, mtime, fit, dither)."""
    source = Path(path)
    fit = fit if fit in FIT_MODES else DEFAULT_FIT
    dither = dither if dither in DITHERS else DEFAULT_DITHER
    stamp = source.stat().st_mtime_ns
    key = hashlib.sha256(
        f"{source.resolve()}|{stamp}|{fit}|{dither}".encode("utf-8")
    ).hexdigest()[:16]
    cached = _CACHE.get(key)
    if cached is not None:
        _CACHE.move_to_end(key)
        return cached

    with Image.open(source) as opened:
        flat = _composite_over_white(opened)
        source_size = flat.size          # as opened, before the rotation
        upright, angle = _upright(flat)
        fitted = _fit(upright, fit)

    if dither == "bayer4":
        bw, red = _planes_bayer(fitted)
    else:
        bw, red = png2epd.to_planes(fitted, dither == "floyd-steinberg")

    result = Render(
        key=key,
        angle=angle,
        source=source_size,
        fitted=fitted.size,
        midtone=_midtone_ratio(fitted),
        bw=bytes(bw),
        red=bytes(red),
        original_png=_png(fitted.convert("RGB")),
        device_png=_png(planes_to_image(bw, red)),
    )
    _CACHE[key] = result
    while len(_CACHE) > _CACHE_MAX:
        _CACHE.popitem(last=False)
    return result


def cached(key: str) -> Render | None:
    """A previously rendered frame, for the PNG endpoints."""
    entry = _CACHE.get(key)
    if entry is None:
        return None
    _CACHE.move_to_end(key)
    return entry


def options() -> dict:
    """What the editor offers, so the page does not hard-code it."""
    return {
        "fits": list(FIT_MODES),
        "dithers": list(DITHERS),
        "default_fit": DEFAULT_FIT,
        "default_dither": DEFAULT_DITHER,
        "panel": [PANEL_W, PANEL_H],
        "midtone_warn": MIDTONE_WARN,
    }
