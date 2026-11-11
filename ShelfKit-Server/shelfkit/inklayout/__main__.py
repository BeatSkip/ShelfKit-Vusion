"""InkLayout from the command line.

    python -m shelfkit.inklayout skill [--display ID] [--orientation landscape] [--out SKILL.md]
    python -m shelfkit.inklayout render layout.xml [--data data.json] [--out screen.png]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="python -m shelfkit.inklayout")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("skill", help="write the skill file for a model")
    s.add_argument("--display")
    s.add_argument("--orientation", choices=("portrait", "landscape"), default="portrait")
    s.add_argument("--out")
    r = sub.add_parser("render", help="render a layout to a PNG and print its problems")
    r.add_argument("layout")
    r.add_argument("--data")
    r.add_argument("--display")
    r.add_argument("--out", default="screen.png")
    args = p.parse_args(argv)

    if args.cmd == "skill":
        from .skill import skill_markdown
        md = skill_markdown(args.display, args.orientation)
        if args.out:
            Path(args.out).write_text(md, encoding="utf-8")
        else:
            sys.stdout.reconfigure(encoding="utf-8")
            sys.stdout.write(md)
        return 0

    from .engine import render
    data = json.loads(Path(args.data).read_text(encoding="utf-8")) if args.data else {}
    result = render(Path(args.layout).read_text(encoding="utf-8"), data, display=args.display)
    result.image.save(args.out)
    for d in result.diagnostics:
        print(f"{d['level']:5} {d['at']}: {d['msg']}")
    print(result.boxes)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
