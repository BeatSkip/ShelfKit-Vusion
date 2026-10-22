#!/usr/bin/env python3
"""Build every firmware target into ready-to-flash Intel HEX files.

    python ShelfKit-Firmware/Tooling/build-all.py
    python ShelfKit-Firmware/Tooling/build-all.py --version 1.2.0
    python ShelfKit-Firmware/Tooling/build-all.py --targets vusion,bootloader

Each target is built with the same flags SDCC-MDF uses, because they are read from
the target's own ``sdcc-project.json`` and the board definition it names:

* ``build.flags`` of the project (the bootloader's ``-Wl-bHOME=0xe400`` lives there),
* CPU, memory model and the IRAM/XRAM/code sizes from the board JSON,
* ``sources`` (directories are walked for ``.c`` and ``.asm``), plus the ``inc``
  folder of every source directory as an include path,
* ``includes``, ``libraries`` (every ``*.lib`` in the listed folders) and
  ``build.output_name``.

The build happens in a temporary directory; the results land in ``Release/`` at the
repository root. Names are stable: ``<target>-latest.hex``, or
``<target>-<version>.hex`` when ``--version`` is given, with the ``.map`` beside it
(which is where you check the placement). Old ``.hex``/``.map`` files in the output
folder are removed first, so a stale build cannot be flashed by mistake and the
folder never accumulates copies. Nothing in ``build/`` is touched, so a VS Code
build and this script never fight over object files.

Requires SDCC on ``PATH`` or in its default Windows install.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIRMWARE = HERE.parent
REPO = FIRMWARE.parent
DEFAULT_OUT = REPO / "Release"
SDCC_DIRS = [Path(r"C:\Program Files\SDCC\bin"), Path(r"C:\Program Files (x86)\SDCC\bin")]
SOURCE_SUFFIXES = {".c", ".asm"}
# folder name -> the name you pass to --targets
TARGETS = {"vusion": "Vusion", "hub": "Vusion-Hub", "bootloader": "Bootloader"}
# shelfota.h OTA_MAX_IMAGE: an application bigger than this cannot be sent over the
# air, even though it still fits when flashed over the wire.
OTA_IMAGE_WINDOW = 0xA7F0


# ── toolchain ──────────────────────────────────────────────────────────────
def find_tool(name: str) -> str:
    found = shutil.which(name)
    if found:
        return found
    for folder in SDCC_DIRS:
        candidate = folder / f"{name}.exe"
        if candidate.is_file():
            return str(candidate)
        candidate = folder / name
        if candidate.is_file():
            return str(candidate)
    raise SystemExit(f"cannot find {name!r}: put SDCC on PATH or install it in {SDCC_DIRS[0].parent}")


def run(command: list[str], what: str) -> None:
    """Run one toolchain step; on failure print what it said and stop."""
    result = subprocess.run(command, capture_output=True, text=True, errors="replace")
    if result.returncode != 0:
        print(f"\n!!! {what} failed (exit {result.returncode})")
        print("    " + " ".join(command))
        for stream in (result.stdout, result.stderr):
            if stream.strip():
                print("\n".join("    " + line for line in stream.strip().splitlines()[-25:]))
        raise SystemExit(1)


# ── the project definition ─────────────────────────────────────────────────
def load_project(root: Path) -> dict:
    path = root / "sdcc-project.json"
    if not path.is_file():
        raise SystemExit(f"{root} has no sdcc-project.json")
    return json.loads(path.read_text(encoding="utf-8"))


def load_board(root: Path, project: dict) -> dict:
    """The board definition the extension would pick: boardsDir from .vscode/settings.json."""
    wanted = project.get("board")
    settings = root / ".vscode" / "settings.json"
    boards_dir = None
    if settings.is_file():
        try:
            boards_dir = json.loads(settings.read_text(encoding="utf-8")).get("sdcc.boardsDir")
        except ValueError:
            boards_dir = None
    folders = [root / boards_dir] if boards_dir else []
    folders += sorted(FIRMWARE.glob("Shared/boards"))
    seen = set()
    for folder in folders:
        if not folder.is_dir() or folder in seen:
            continue
        seen.add(folder)
        for candidate in sorted(folder.glob("*.json")):
            try:
                board = json.loads(candidate.read_text(encoding="utf-8"))
            except ValueError:
                continue
            if board.get("build", {}).get("mcu") == wanted:
                return board
    raise SystemExit(f"no board definition for {wanted!r} in {[str(f) for f in folders]}")


def board_flags(board: dict) -> list[str]:
    build = board.get("build", {})
    memory = build.get("memory", {})
    flags = [f"-m{build.get('cpu', 'mcs51')}"]
    if build.get("memory_model"):
        flags.append(f"--model-{build['memory_model']}")
    for key, option in (("size_iram", "--iram-size"), ("size_xram", "--xram-size"),
                        ("size_code", "--code-size")):
        if memory.get(key) is not None:
            flags += [option, str(memory[key])]
    flags += [str(extra) for extra in build.get("extra_flags") or []]
    return flags


def collect(root: Path, project: dict) -> tuple[list[Path], list[str], list[Path]]:
    """Sources (walked), include paths (with each source dir's inc/) and libraries."""
    sources: list[Path] = []
    includes: list[str] = []
    for entry in project.get("sources") or []:
        path = (root / entry).resolve()
        if path.is_dir():
            for child in sorted(path.rglob("*")):
                if child.is_file() and child.suffix.lower() in SOURCE_SUFFIXES:
                    sources.append(child)
            for inc in (path / "inc", path / "include"):
                if inc.is_dir():
                    includes.append(str(inc))
        elif path.is_file():
            sources.append(path)
        else:
            raise SystemExit(f"{root} lists a source that does not exist: {entry}")

    for entry in project.get("includes") or []:
        path = (root / entry).resolve()
        if not path.is_dir():
            raise SystemExit(f"{root} lists an include folder that does not exist: {entry}")
        includes.append(str(path))

    libraries: list[Path] = []
    for entry in project.get("libraries") or []:
        path = (root / entry).resolve()
        if path.is_dir():
            libraries.extend(sorted(path.glob("*.lib")))
        elif path.is_file():
            libraries.append(path)

    # de-duplicate, keep order
    includes = list(dict.fromkeys(includes))
    return sources, includes, libraries


# ── naming ─────────────────────────────────────────────────────────────────
def git(*args: str) -> str:
    try:
        result = subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True)
    except OSError:
        return ""
    return result.stdout.strip() if result.returncode == 0 else ""


def build_stem(name: str, version: str | None) -> str:
    """``<name>-<version>``, or ``<name>-latest`` when no version was given."""
    return f"{name}-{version}" if version else f"{name}-latest"


def slug(name: str) -> str:
    """Vusion-Hub -> vusion-hub: the release name comes from the target folder, not
    from build.output_name (Vusion and Vusion-Hub both call their build 'firmware')."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def display(path: Path) -> str:
    """Repo-relative when possible - --out may point anywhere."""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def mem_usage(map_mem: Path) -> str:
    """'code 37866/59389, xram 1047/8192' from the .mem report, when it exists."""
    try:
        text = map_mem.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    code = re.search(r"ROM/EPROM/FLASH\s+0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+(\d+)\s+(\d+)", text)
    xram = re.search(r"EXTERNAL RAM\s+0x[0-9A-Fa-f]+\s+0x[0-9A-Fa-f]+\s+(\d+)\s+(\d+)", text)
    parts = []
    if code:
        parts.append(f"code {code.group(1)}/{code.group(2)}")
    if xram:
        parts.append(f"xram {xram.group(1)}/{xram.group(2)}")
    return ", ".join(parts)


# ── one target ─────────────────────────────────────────────────────────────
def build_target(folder: str, out_dir: Path, version: str | None, clean: bool) -> dict:
    root = FIRMWARE / folder
    project = load_project(root)
    board = load_board(root, project)
    sources, includes, libraries = collect(root, project)

    build = project.get("build") or {}
    name = build.get("output_name") or "firmware"
    flags = board_flags(board) + [str(flag) for flag in build.get("flags") or []]
    defines = [f"-D{d}" for d in project.get("defines") or []]
    include_flags = [f"-I{inc}" for inc in includes]

    sdcc = find_tool("sdcc")
    work = Path(tempfile.mkdtemp(prefix=f"sk-build-{name}-"))
    try:
        print(f"\n=== {folder}  ({name}, {len(sources)} sources) ===")
        objects: list[Path] = []
        for index, source in enumerate(sources, 1):
            relative = source.relative_to(root) if root in source.parents else source.name
            obj = work / f"{index:03d}-{source.stem}.rel"
            if source.suffix.lower() == ".asm":
                run([find_tool("sdas8051"), "-plosgffw", str(obj), str(source)],
                    f"assemble {relative}")
            else:
                run([sdcc, *flags, *defines, *include_flags, "-c", str(source), "-o", str(obj)],
                    f"compile {relative}")
            objects.append(obj)
            print(f"  {str(relative):<52} ok")

        ihx = work / f"{name}.ihx"
        run([sdcc, *flags, *defines, *include_flags, *map(str, objects), *map(str, libraries),
             "-o", str(ihx)], "link")
        hex_file = out_dir / f"{build_stem(slug(folder), version)}.hex"
        if hex_file.exists():
            hex_file.unlink()       # re-running replaces that day's file, never appends
        packed = subprocess.run([find_tool("packihx"), str(ihx)], capture_output=True, text=True)
        if packed.returncode != 0 or not packed.stdout.strip():
            print(f"\n!!! packihx failed for {name}")
            print(packed.stderr.strip())
            raise SystemExit(1)
        hex_file.write_text(packed.stdout, encoding="utf-8")

        # the .map explains the placement (and the .mem the budget); keep both next door
        map_file = hex_file.with_suffix(".map")
        source_map = ihx.with_suffix(".map")
        if source_map.is_file():
            shutil.copyfile(source_map, map_file)
        usage = mem_usage(ihx.with_suffix(".mem"))
        digest = hashlib.sha256(hex_file.read_bytes()).hexdigest()[:16]
        size = hex_file.stat().st_size
        print(f"  -> {display(hex_file)}  {size} bytes  sha256:{digest}  {usage}")
        code = 0
        if usage:
            try:
                code = int(usage.split()[1].split("/")[0]) if usage.startswith("code ") else 0
            except (IndexError, ValueError):
                code = 0
        return {"target": folder, "hex": hex_file, "bytes": size, "sha256": digest,
                "usage": usage, "code": code}
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ── one HEX with both images in it ─────────────────────────────────────────
# Where the bootloader's own code lives; keep in sync with -Wl-bHOME in the
# Bootloader project and with `_jmp_vector` in its main.c.
BOOT_BASE = 0xD800
APP_VECTOR = 0xD7FE


def read_hex(path: Path) -> dict[int, int]:
    """Intel HEX -> {address: byte}. Gaps stay gaps; nothing is filled in."""
    cells: dict[int, int] = {}
    base = 0
    for number, line in enumerate(path.read_text(encoding="ascii", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        if not line.startswith(":"):
            raise SystemExit(f"{path}:{number}: not an Intel HEX record")
        raw = bytes.fromhex(line[1:])
        if sum(raw) & 0xFF:
            raise SystemExit(f"{path}:{number}: bad checksum")
        count, addr, rtype = raw[0], (raw[1] << 8) | raw[2], raw[3]
        payload = raw[4:4 + count]
        if rtype == 0x00:
            for i, byte in enumerate(payload):
                at = base + addr + i
                if at in cells and cells[at] != byte:
                    raise SystemExit(f"{path}:{number}: 0x{at:04X} appears twice with different data")
                cells[at] = byte
        elif rtype == 0x01:
            break
        elif rtype == 0x02:
            base = ((payload[0] << 8) | payload[1]) << 4
        elif rtype == 0x04:
            base = ((payload[0] << 8) | payload[1]) << 16
    return cells


def hex_runs(addresses: list[int]) -> list[tuple[int, int]]:
    """Sorted addresses -> the contiguous [start, end] runs they form."""
    runs: list[tuple[int, int]] = []
    for addr in addresses:
        if runs and addr == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], addr)
        else:
            runs.append((addr, addr))
    return runs


def write_hex(cells: dict[int, int], record: int = 16) -> str:
    """{address: byte} -> Intel HEX, ascending, one record per 16-byte slice of a run."""
    out = []
    for start, end in hex_runs(sorted(cells)):
        addr = start
        while addr <= end:
            n = min(record, end - addr + 1)
            data = bytes(cells[a] for a in range(addr, addr + n))
            body = bytes([n, (addr >> 8) & 0xFF, addr & 0xFF, 0x00]) + data
            out.append(":" + (body + bytes([(-sum(body)) & 0xFF])).hex().upper())
            addr += n
    out.append(":00000001FF")
    return "\n".join(out) + "\n"


def bundle(tag_hex: Path, boot_hex: Path, out_dir: Path, version: str | None) -> Path:
    """Merge the bootloader and the application into the HEX one flash run needs.

    Two things make this more than a concatenation:

    * Address 0x0000 belongs to the *bootloader's* reset jump, not the
      application's: the application's own three bytes are dropped, otherwise
      flashing both would leave the chip booting straight into the app and the
      bootloader would never run (so no OTA, no serial update path).
    * The application's entry address is installed in the bootloader's jump
      vector at 0xD7FE, exactly as `ota_program()` does after an OTA image - so
      a freshly flashed tag starts its application immediately.
    """
    boot = read_hex(boot_hex)
    app = read_hex(tag_hex)

    if not boot:
        raise SystemExit(f"{boot_hex} is empty")
    if not app:
        raise SystemExit(f"{tag_hex} is empty")
    if app.get(0) != 0x02:
        raise SystemExit(f"{tag_hex}: the application does not start with a reset jump")
    entry = (app[1] << 8) | app[2]
    app = {a: b for a, b in app.items() if a > 2}

    high = max(boot)
    if high >= 0x10000:
        raise SystemExit(f"{boot_hex}: address 0x{high:04X} is not internal flash")
    if min(boot) != 0 or not all(a < 3 or a >= BOOT_BASE for a in boot):
        raise SystemExit(f"{boot_hex}: expected only the vector at 0 and code from 0x{BOOT_BASE:04X}")
    if max(app) >= BOOT_BASE:
        raise SystemExit(f"{tag_hex}: the application runs into the bootloader at 0x{BOOT_BASE:04X}")

    overlap = set(app) & set(boot)
    if overlap:
        raise SystemExit(f"the two images overlap at 0x{min(overlap):04X}")
    if APP_VECTOR in boot or APP_VECTOR in app or APP_VECTOR + 1 in app:
        raise SystemExit(f"the jump vector at 0x{APP_VECTOR:04X} is already occupied")

    merged = dict(boot)
    merged.update(app)
    merged[APP_VECTOR] = entry & 0xFF        # run_application() reads low byte first
    merged[APP_VECTOR + 1] = entry >> 8

    name = build_stem("vusion-full", version)
    target = out_dir / f"{name}.hex"
    target.write_text(write_hex(merged), encoding="utf-8")
    print(f"\n=== one HEX for both ===")
    print(f"  {display(target)}")
    print(f"  bootloader 0x{BOOT_BASE:04X}..0x{max(boot):04X}  ({len(boot)} bytes)")
    print(f"  application 0x0003..0x{max(app):04X}  ({len(app)} bytes, entry 0x{entry:04X})")
    print(f"  jump vector 0x{APP_VECTOR:04X} = {entry & 0xFF:02X} {entry >> 8:02X}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--targets", default="all",
                        help="comma separated: " + ", ".join(TARGETS) + " (default all)")
    parser.add_argument("--version",
                        help="name the files <target>-<version>.hex (default: <target>-latest.hex)")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"output folder (default {DEFAULT_OUT})")
    parser.add_argument("--clean", action="store_true",
                        help="accepted for compatibility; old .hex/.map are always removed")
    parser.add_argument("--no-bundle", action="store_true",
                        help="do not also write the bootloader+application HEX")
    args = parser.parse_args(argv)

    if args.targets.strip().lower() == "all":
        chosen = list(TARGETS.values())
    else:
        wanted = [part.strip().lower() for part in args.targets.split(",") if part.strip()]
        unknown = [w for w in wanted if w not in TARGETS]
        if unknown:
            parser.error(f"unknown target(s) {unknown}; pick from {list(TARGETS)}")
        chosen = [TARGETS[w] for w in wanted]

    out_dir = Path(args.out).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    # Always: the names are stable now, so a leftover build would sit next to the
    # fresh one and invite flashing the wrong file.
    for stale in [*out_dir.glob("*.hex"), *out_dir.glob("*.map")]:
        stale.unlink()

    print(f"SDCC {find_tool('sdcc')}")
    print(f"output {out_dir}")
    results = [build_target(folder, out_dir, args.version, args.clean) for folder in chosen]

    if not args.no_bundle and "Vusion" in chosen and "Bootloader" in chosen:
        by_target = {row["target"]: row["hex"] for row in results}
        try:
            full_hex = bundle(by_target["Vusion"], by_target["Bootloader"],
                              out_dir, args.version)
        except SystemExit as exc:
            print(f"\n!!! could not bundle: {exc}")

    for row in results:
        if row["target"] == "Vusion" and row.get("code", 0) > OTA_IMAGE_WINDOW:
            print(f"\n!!! the tag image is {row['code']} B, over the {OTA_IMAGE_WINDOW} B OTA window:")
            print("    it flashes over the wire, but ota-send.py and the server will refuse it.")
            print("    Free space in the application, or move bytes out of it.")

    print("\n=== ready to flash ===")
    for row in results:
        print(f"  {row['hex'].name:<44} {row['bytes']:>8} bytes  {row['usage']}")
    full = locals().get("full_hex")
    hub = next((row["hex"] for row in results if row["target"] == "Vusion-Hub"), None)
    if full is not None:
        print(f"\nTag:  python {HERE / 'axsem-flasher.py'} {full} -p COM4")
        print("      (the full image: bootloader + application + the reset vector that")
        print("       points at the bootloader. Flashing vusion-*.hex alone overwrites")
        print("       0x0000 with an ljmp to the application and BYPASSES the bootloader,")
        print("       so OTA updates can never be applied.)")
    if hub is not None:
        print(f"Hub:  python {HERE / 'axsem-flasher.py'} {hub} -p COM4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
