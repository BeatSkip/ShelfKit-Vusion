"""Display presets: the panels a tag can carry.

A preset is what a drawing needs to know about a panel: its pixel size (in the
orientation the image pipeline works in) and the colours it can show. Apps draw
on a canvas built from the tag's preset, so supporting another shelf label means
adding a preset here, not touching any app that only reads `canvas.width` /
`canvas.height`.

Today every tag is the Vusion 2.6" BWR, and the push pipeline below this
(png2epd, preview, eco, hubhost) is still fixed to its 152x296 frame. A second
panel therefore needs both a preset here and that pipeline taught its size and
colours; until then the default preset is the only one that can be pushed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

RGB = tuple[int, int, int]


@dataclass(frozen=True)
class DisplayPreset:
    id: str                      # stable key, stored per tag later on
    name: str                    # for people
    width: int                   # pixels, in the pipeline's (upright) orientation
    height: int
    colors: dict[str, RGB] = field(default_factory=dict)   # name -> RGB the panel can show

    def as_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "width": self.width, "height": self.height,
                "colors": {k: list(v) for k, v in self.colors.items()}}


_PRESETS: dict[str, DisplayPreset] = {}


def register(p: DisplayPreset) -> DisplayPreset:
    _PRESETS[p.id] = p
    return p


VUSION_26_BWR = register(DisplayPreset(
    id="vusion-2.6-bwr",
    name='SES-imagotag Vusion 2.6" BWR (GDEW026Z39)',
    width=152, height=296,
    colors={"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0)},
))

DEFAULT_PRESET = VUSION_26_BWR.id


def preset(preset_id: str | None) -> DisplayPreset:
    """The preset with this id, or the default one for an unknown or missing id."""
    return _PRESETS.get(preset_id or "", _PRESETS[DEFAULT_PRESET])


def presets() -> list[dict]:
    return [p.as_dict() for p in _PRESETS.values()]
