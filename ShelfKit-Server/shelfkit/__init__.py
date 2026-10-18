"""Supporting modules for the ShelfKit-Server entry point.

Only `../shelfkit-server.py` is meant to be run; it pulls in these:

    app          the state behind the page: panes, logs, tags, image push
    serial_link  ports, handshake lines and the per-port reader thread
    webapp       the HTTP/JSON layer that turns `app` into a browser UI
    static/      the page itself (index.html, app.js, style.css)
    hubhost      the hub's command channel and image framing (also a CLI)
    png2epd      PNG -> the two 1-bit planes the tag streams into the panel

Nothing is imported here, so `shelfkit.hubhost` stays usable when Pillow is
missing (only the image conversion needs it).
"""
