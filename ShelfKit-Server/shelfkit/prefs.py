"""Page settings that outlive a browser: one validated dict, kept in the settings table.

Everything here is something the Settings screen edits. Unknown keys and out-of-range
values are dropped rather than stored, so a bad request can never leave the page with
numbers it cannot draw (a "late" window longer than "silent", say).

Alias import/export is here too, because it is the other thing Settings does: a CSV of
`hex_id,alias,notes,shelf,slot` that round-trips through the same tag metadata the
inspector edits.
"""

from __future__ import annotations

import csv
import io

SETTING_KEY = "prefs"

DEFAULTS = {
    "late_after_s": 330,      # slower than the idle poll rate (300 s) + slack
    "silent_after_s": 630,    # slower than the weak-link poll rate (600 s) + slack
    "forget_after_s": 900,    # "forget silent tags" cutoff, past the slowest poll
    "low_battery_v": 2.5,     # below this a CR2450 is close to done
    "fleet_view": "wall",     # wall | table
    "wall_size": "full",      # full | half
    "axsdb_path": "",         # axsdb.exe, or its folder; empty = look for it
    "show_tag_port": True,    # the optional tag debug serial pane on the Hub screen
}
# The hub's and the tag's serial ports are also set from the Settings screen, but they
# live with the panes (see App._plan_ports), not in this dict.

# (min, max) for the numeric ones
RANGES = {
    "late_after_s": (60, 7200),
    "silent_after_s": (120, 14400),
    "forget_after_s": (300, 86400),
    "low_battery_v": (2.0, 3.2),
}
BOOLS = ("show_tag_port",)
STRINGS = {"axsdb_path": 400}      # name -> longest value
CHOICES = {
    "fleet_view": ("wall", "table"),
    "wall_size": ("full", "half"),
}


def clean(options: dict, current: dict | None = None) -> tuple[dict, list[str]]:
    """Merge `options` over `current` (or the defaults); return (prefs, problems)."""
    prefs = dict(DEFAULTS)
    prefs.update({k: v for k, v in (current or {}).items() if k in DEFAULTS})
    problems: list[str] = []
    for name, value in (options or {}).items():
        if name not in DEFAULTS:
            continue
        if name in BOOLS:
            if isinstance(value, bool):
                prefs[name] = value
            else:
                problems.append(f"{name} must be true or false")
            continue
        if name in STRINGS:
            if not isinstance(value, str) or len(value.strip()) > STRINGS[name]:
                problems.append(f"{name} must be text of at most {STRINGS[name]} characters")
            else:
                prefs[name] = value.strip().strip('"')
            continue
        if name in CHOICES:
            if value in CHOICES[name]:
                prefs[name] = value
            else:
                problems.append(f"{name} must be one of {', '.join(CHOICES[name])}")
            continue
        try:
            number = float(value) if name == "low_battery_v" else int(float(value))
        except (TypeError, ValueError):
            problems.append(f"{name} must be a number")
            continue
        low, high = RANGES[name]
        if not low <= number <= high:
            problems.append(f"{name} must be between {low} and {high}")
            continue
        prefs[name] = round(number, 2) if name == "low_battery_v" else number
    # the windows only make sense in order
    if not prefs["late_after_s"] < prefs["silent_after_s"] < prefs["forget_after_s"]:
        problems.append("the times must run in order: late, then silent, then forget")
        prefs = {**prefs, **{k: (current or DEFAULTS).get(k, DEFAULTS[k])
                             for k in ("late_after_s", "silent_after_s", "forget_after_s")}}
    return prefs, problems


def aliases_to_csv(rows: list[dict]) -> str:
    """rows: {"hex", "alias", "notes", "row", "col"} per tag, in tag order."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(["hex_id", "alias", "notes", "shelf", "slot"])
    for row in rows:
        writer.writerow([row["hex"], row.get("alias") or "", row.get("notes") or "",
                         "" if row.get("row") is None else row["row"],
                         "" if row.get("col") is None else row["col"]])
    return out.getvalue()


def parse_aliases(text: str) -> tuple[list[dict], list[str]]:
    """Parse a CSV in the export's layout. Returns (entries, problems)."""
    entries: list[dict] = []
    problems: list[str] = []
    reader = csv.reader(io.StringIO(text.lstrip("﻿")))
    for number, cells in enumerate(reader, start=1):
        if not any(cell.strip() for cell in cells):
            continue
        first = cells[0].strip()
        if number == 1 and first.lower() in ("hex_id", "hex", "id", "tag"):
            continue                                    # the header row
        try:
            addr = int(first, 16)
            if not 0 < addr <= 0xFFFF:
                raise ValueError
        except ValueError:
            problems.append(f"line {number}: {first or '(empty)'!r} is not a hex tag ID")
            continue
        cells = [cell.strip() for cell in cells] + [""] * 5
        entry = {"hex": f"{addr:04X}", "alias": cells[1][:24], "notes": cells[2][:120]}
        for key, cell in (("grid_row", cells[3]), ("grid_col", cells[4])):
            if cell == "":
                entry[key] = None
                continue
            try:
                entry[key] = int(cell)
            except ValueError:
                problems.append(f"line {number}: shelf and slot must be whole numbers")
                entry = None
                break
        if entry:
            entries.append(entry)
    return entries, problems
