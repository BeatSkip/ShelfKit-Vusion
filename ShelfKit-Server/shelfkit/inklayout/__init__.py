"""InkLayout: a screen description language that always renders sharply on e-ink.

    from shelfkit.inklayout import render
    result = render('<screen><text size="16">Hello</text></screen>', data={...})
    result.image        # PIL image in the display's colours only
    result.diagnostics  # [{"level", "at", "msg"}] - what to change, in words
    result.boxes        # the layout as text, for a reader without eyes

See Documentation/InkLayout.md.
"""

from . import icons
from .engine import ALLOWED_SIZES, ELEMENTS, LayoutResult, render

__all__ = ["ALLOWED_SIZES", "ELEMENTS", "LayoutResult", "icons", "render"]
# the skill file generator is a submodule: from shelfkit.inklayout import skill
