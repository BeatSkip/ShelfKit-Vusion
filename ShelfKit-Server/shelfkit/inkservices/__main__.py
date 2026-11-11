"""Render an app's screen to a PNG, without a server, store or tag:

    cd ShelfKit-Server
    python -m shelfkit.inkservices render hello --out hello.png
    python -m shelfkit.inkservices render hello --tag 0101 --alias "Kitchen" --data '{"n": 7}'
    python -m shelfkit.inkservices list

The tag context is made up from the options (defaults: id 0000, the default
display preset, the app's config defaults, empty data); nothing is stored.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .. import displays
from .loader import INKAPPS_DIR, load_apps
from .screen import AppError, LayoutError, draw_screen
from .sdk import TagContext


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m shelfkit.inkservices")
    ap.add_argument("--apps", default=str(INKAPPS_DIR), help="the inkapps folder")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list the apps and whether they load")
    r = sub.add_parser("render", help="render an app's screen to a PNG")
    r.add_argument("app")
    r.add_argument("--tag", default="0000")
    r.add_argument("--alias")
    r.add_argument("--display", default=displays.DEFAULT_PRESET,
                   choices=[p["id"] for p in displays.presets()])
    r.add_argument("--data", default="{}", help="the tag's data, as JSON")
    r.add_argument("--config", default="{}", help="the tag's settings, as JSON")
    r.add_argument("--out", help="PNG to write (default <app>.png)")
    r.add_argument("--boxes", action="store_true", help="print the layout's box picture")
    args = ap.parse_args(argv)

    apps = load_apps(Path(args.apps))
    if args.cmd == "list":
        for item in apps.values():
            print(f"{item.id:<16} {'ok' if item.app else 'ERROR ' + str(item.error)}")
        return 0

    item = apps.get(args.app)
    if item is None:
        print(f"no app {args.app!r} in {args.apps}", file=sys.stderr)
        return 2
    if item.app is None:
        print(f"{args.app} did not load: {item.error}", file=sys.stderr)
        return 2
    app = item.app
    tag = TagContext(
        hex_id=args.tag.upper(), alias=args.alias, notes=None,
        config={**app.config_defaults(), **json.loads(args.config)},
        data=json.loads(args.data), shared={}, db=None, battery=None,
        display=displays.preset(args.display),
    )
    try:
        image, result = draw_screen(app, tag)
    except LayoutError as exc:
        for d in exc.result.diagnostics:
            print(f"{d['level']}: {d['at']}: {d['msg']}", file=sys.stderr)
        return 1
    except AppError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    out = Path(args.out or f"{app.id}.png")
    image.save(out, format="PNG")
    for _, line in tag.logs:
        print(f"log: {line}")
    if result is not None:
        for d in result.diagnostics:
            print(f"{d['level']}: {d['at']}: {d['msg']}")
        if args.boxes:
            print(result.boxes)
    print(f"wrote {out} ({image.width}x{image.height}, {tag.display.id})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
