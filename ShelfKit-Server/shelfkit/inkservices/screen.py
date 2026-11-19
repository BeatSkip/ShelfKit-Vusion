"""Turn an app plus a TagContext into the tag's screen image.

One place for both ways an app can draw, used by the host and the render CLI alike:

* `@app.render`            - Python on a Canvas,
* `InkApp(layout="x.xml")` - an InkLayout file filled with `@app.data` (or tag.data).

A layout with errors is not pushed: a half-understood screen on a shelf is worse
than the previous one. Its warnings are returned so the host can log them.
"""

from __future__ import annotations

import re

from PIL import Image

from .. import inklayout
from .canvas import Canvas
from .sdk import InkApp, TagContext


class AppError(Exception):
    """Something the caller should show: the app is missing, broken, or raised."""


class LayoutError(AppError):
    def __init__(self, result) -> None:
        errors = [d for d in result.diagnostics if d["level"] == "error"]
        super().__init__("layout: " + "; ".join(f"{d['at']}: {d['msg']}" for d in errors[:3]))
        self.result = result


def tag_view(tag: TagContext) -> dict:
    """What a layout may read as `tag`."""
    return {"hex_id": tag.hex_id, "id": tag.hex_id, "alias": tag.alias or tag.hex_id,
            "notes": tag.notes or "", "battery": tag.battery, "config": tag.config,
            "display": tag.display.id}


def screen_orientation(app: InkApp, chosen: str | None = None) -> str:
    """How the app's screen sits: the owner's choice, else InkApp(orientation=), else what
    the layout's <screen orientation=> says, else portrait."""
    if chosen or app.orientation:
        return chosen or app.orientation
    path = app.layout_path() if app.render_fn is None else None
    try:
        if path is not None and re.search(r'<screen\b[^>]*\borientation\s*=\s*"landscape"',
                                          path.read_text(encoding="utf-8")):
            return "landscape"
    except OSError:
        pass
    return "portrait"


def draw_screen(app: InkApp, tag: TagContext,
                orientation: str | None = None) -> tuple[Image.Image, object | None]:
    """(image, layout result or None), drawn upright. `orientation` (any of
    sdk.ORIENTATIONS) overrides the app's and the layout's; the caller turns a "-flipped"
    one over for the glass. Raises AppError for anything the app got wrong; exceptions from
    the app's own code pass through for the caller to log."""
    chosen = orientation or app.orientation
    base = chosen.split("-")[0] if chosen else None
    if app.render_fn is not None:
        canvas = Canvas(tag.display, landscape=None if base is None else base == "landscape")
        app.render_fn(tag, canvas)
        return canvas.image, None

    path = app.layout_path()
    if path is None:
        raise AppError(f"app {app.id!r} has neither @app.render nor layout=")
    if not path.is_file():
        raise AppError(f"layout file {app.layout!r} not found in {app.folder}")
    data = app.data_fn(tag) if app.data_fn is not None else tag.data
    if not isinstance(data, dict):
        raise AppError(f"@app.data must return a dict, not {type(data).__name__}")
    result = inklayout.render(path.read_text(encoding="utf-8"), data, tag=tag_view(tag),
                              display=tag.display.id, now=tag.now, shared=tag.shared,
                              orientation=base)
    if not result.ok:
        raise LayoutError(result)
    return result.image, result
