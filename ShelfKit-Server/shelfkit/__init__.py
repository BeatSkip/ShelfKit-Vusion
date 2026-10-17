"""Supporting modules for the ShelfKit-Server entry point.

Only `../shelfkit-server.py` is meant to be run; it pulls in these:

    hubhost   the hub's command channel, the image framing and the CLI
              (`serve` / `send` / `ping`) - also usable on its own
    png2epd   PNG -> the two 1-bit planes the tag streams into the panel

Nothing is imported here, so `shelfkit.hubhost` stays usable when Pillow is
missing (only the image conversion needs it).
"""
