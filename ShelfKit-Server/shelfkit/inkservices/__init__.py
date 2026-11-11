"""InkServices: small Python apps that own a tag's screen.

See Documentation/InkServices.md (the idea) and Documentation/plans/2026-11-11-inkservices.md
(how it is built). An app imports everything it needs from here.
"""

from .canvas import BLACK, RED, WHITE, Canvas
from .sdk import ConfigField, Control, InkApp, TagContext, Timer

__all__ = ["BLACK", "RED", "WHITE", "Canvas", "ConfigField", "Control", "InkApp", "TagContext", "Timer"]
