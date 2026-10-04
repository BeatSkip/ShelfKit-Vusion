"""Make shared/lib/libmf.lib linkable by more than one wtimer/radio module at a time.

The vendor makefiles compile libmf with `--debug`, so every module that inlines the
critical-section helpers from libmftypes.h carries the same global debug line labels
(`C$libmftypes.h$351$4$73`, ...). Linking two such modules - any radio firmware does,
e.g. wtcbadd + wt0adda - prints "Multiple definition of C$..." and makes SDCC exit
with status 1, which SDCC-MDF treats as a failed build.

The labels are debug-only and nothing references them, so this script renames the
repeats in place, replacing the first character ('C') with 'D', 'E', ... for the 2nd,
3rd, ... module that defines the same label. Names keep their length, so the index
offsets inside the archive stay valid. Idempotent: a patched archive has no repeats left.

    python tooling/patch_libmf_labels.py [path/to/libmf.lib]
"""

import re
import sys
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent.parent / "shared" / "lib" / "libmf.lib"

FILE_RE = re.compile(rb"<FILE>\r?\n([^\r\n]+)\r?\n<REL>")
LABEL_RE = re.compile(rb"(?m)^S (C\$[^\s]+) Def")


def patch(data: bytes) -> tuple[bytes, int]:
    files_at = data.index(b"<FILES>")
    head, body = data[:files_at], bytearray(data[files_at:])

    modules = [(m.start(), m.group(1)) for m in FILE_RE.finditer(body)]
    modules.append((len(body), b""))

    seen: dict[bytes, int] = {}
    renamed = 0
    for (start, _name), (end, _next) in zip(modules, modules[1:]):
        # a label repeated inside one module is the compiler's own business
        in_module = set()
        for m in LABEL_RE.finditer(body, start, end):
            label = m.group(1)
            if label in in_module:
                continue
            in_module.add(label)
            n = seen.get(label, 0)
            seen[label] = n + 1
            if n:
                if n > 8:
                    raise SystemExit(f"{label!r} defined in more than 9 modules")
                pos = m.start(1)
                body[pos] = ord("C") + n
                renamed += 1
    return head + bytes(body), renamed


def main() -> None:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    data = path.read_bytes()
    patched, renamed = patch(data)
    assert len(patched) == len(data)
    if renamed:
        path.write_bytes(patched)
    print(f"{path}: {renamed} duplicate label(s) renamed")


if __name__ == "__main__":
    main()
