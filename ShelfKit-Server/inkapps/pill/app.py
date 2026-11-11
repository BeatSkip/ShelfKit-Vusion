"""pill - log the contraceptive pill with an NFC tap (Documentation/InkServices.md, idea 1).

Tap the tag with your phone: today's pill is logged with the time, and the tag shows
the month as a grid (taken days in black, missed days in red, today ringed in red)
with when the last pill was taken. After the reminder time an untaken pill turns the
bottom bar red. A pack with a pill-free week (21 + 7) is set with two settings.

Taps are the main input; the phone page also has "Taken" (for a phone without NFC)
and "Undo last" (for a tap by mistake). The screen shows no clock: it changes only
when a pill is logged, the day turns or the reminder time passes, so the tag is only
sent a picture then.
"""

from __future__ import annotations

import calendar
from datetime import date, datetime, time

from shelfkit.inkservices import InkApp

app = InkApp("pill", title="Pill tracker",
             description="Tap the tag with your phone when you take your pill.",
             layout="layout.xml")
app.config_field("remind_at", label="Remind after (HH:MM)", default="20:00")
app.config_field("pack_start", label="First day of the current pack (YYYY-MM-DD)", default="")
app.config_field("break_days", label="Pill-free days per 28-day pack (0 or 7)", default="0")

KEEP = 400                      # pills remembered (over a year)
WEEKDAYS = ["M", "T", "W", "T", "F", "S", "S"]


# ── reading the settings and the log ─────────────────────────────────────────
def _now(tag) -> datetime:
    now = tag.now
    return now.astimezone().replace(tzinfo=None) if now.tzinfo else now


def _taken(tag) -> list[datetime]:
    out = []
    for raw in tag.data.get("taken", []):
        try:
            out.append(datetime.fromisoformat(raw))
        except (TypeError, ValueError):
            pass
    return sorted(out)


def _remind_at(tag) -> time:
    try:
        hh, mm = str(tag.config.get("remind_at") or "").split(":")
        return time(int(hh), int(mm))
    except ValueError:
        return time(20, 0)


def _is_break(tag, day: date) -> bool:
    try:
        start = date.fromisoformat(str(tag.config.get("pack_start") or ""))
        brk = int(tag.config.get("break_days") or 0)
    except ValueError:
        return False
    if not 0 < brk < 28:
        return False
    return (day - start).days % 28 >= 28 - brk


# ── what the screen shows ───────────────────────────────────────────────────
def _cell(n: int = 0, *, taken=False, missed=False, today=False, brk=False) -> dict:
    """How one day looks. The three colours form a hierarchy: a taken pill is the
    heaviest mark (solid black), a missed one the loudest (solid red), today is a red
    ring, and days still to come stay quiet (a plain number). Pill-free days are dotted
    and carry no number: text on a pattern is unreadable on e-ink."""
    if not n:
        return {"n": 0, "show": False, "bg": "white", "fg": "black", "border": "none",
                "bold": False}
    show, bold = True, False
    if taken:
        bg, fg, border, bold = "black", "white", "2 red" if today else "none", True
    elif missed:
        bg, fg, border, bold = "red", "white", "none", True
    elif brk:
        bg, fg, border, show = "dots", "black", "2 red" if today else "none", False
    elif today:
        bg, fg, border, bold = "white", "black", "2 red", True
    else:
        bg, fg, border = "white", "black", "none"
    return {"n": n, "show": show, "bg": bg, "fg": fg, "border": border, "bold": bold,
            "taken": taken, "missed": missed, "today": today, "brk": brk}


@app.data
def data(tag):
    now = _now(tag)
    today = now.date()
    taken = _taken(tag)
    days_taken = {t.date() for t in taken}
    first = taken[0].date() if taken else None

    cells = [_cell() for _ in range(date(today.year, today.month, 1).weekday())]
    for n in range(1, calendar.monthrange(today.year, today.month)[1] + 1):
        day = date(today.year, today.month, n)
        brk = _is_break(tag, day)
        missed = (first is not None and first <= day < today and not brk
                  and day not in days_taken)
        cells.append(_cell(n, taken=day in days_taken, missed=missed, today=day == today,
                           brk=brk))
    cells += [_cell() for _ in range(-len(cells) % 7)]

    remind = _remind_at(tag)
    if today in days_taken:
        status = "taken"
    elif _is_break(tag, today):
        status = "break"
    elif now.time() >= remind:
        status = "late"
    else:
        status = "due"

    last = taken[-1] if taken else None
    month_days = [c for c in cells if c["n"]]
    return {
        "month": now.strftime("%B"),
        "taken_count": sum(1 for c in month_days if c["taken"]),
        "missed_count": sum(1 for c in month_days if c["missed"]),
        "weekdays": WEEKDAYS,
        "cells": cells,
        "last_date": last.strftime("%a %d %b") if last else "Not yet",
        "last_time": last.strftime("%H:%M") if last else "--:--",
        "status": status,
        "remind_at": remind.strftime("%H:%M"),
    }


# ── what the phone does ─────────────────────────────────────────────────────
def _log_pill(tag) -> None:
    now = _now(tag)
    if any(t.date() == now.date() for t in _taken(tag)):
        tag.log("already logged today")
        return
    tag.data["taken"] = (tag.data.get("taken", []) + [now.isoformat(timespec="minutes")])[-KEEP:]
    tag.log(f"pill logged {now:%H:%M}")


@app.on_open
def tapped(tag):
    _log_pill(tag)


@app.button("Taken")
def taken_button(tag):
    _log_pill(tag)


@app.button("Undo last", id="undo")
def undo(tag):
    taken = tag.data.get("taken", [])
    if taken:
        tag.log(f"removed {taken.pop()}")
    tag.data["taken"] = taken


@app.every(minutes=15)
def tick(tag):
    """Nothing to fetch: this only lets the screen follow the day and the reminder."""
