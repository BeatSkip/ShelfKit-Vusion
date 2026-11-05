"""Render a panel-sized status frame (152x296, black/white/red) from this machine's stats.

Used by `hubhost.py PORT stats`. Needs only Pillow; psutil is used when installed
(CPU load, uptime) and the standard library covers the rest, so it also runs on Windows.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import time
from datetime import datetime

from PIL import Image, ImageDraw

try:
    from .service_image import BLACK, HEIGHT, RED, WHITE, WIDTH, _font, _fits
except ImportError:                 # run as a script from the shelfkit folder
    from service_image import BLACK, HEIGHT, RED, WHITE, WIDTH, _font, _fits

WARN_PCT = 85


def _mem_pct() -> float | None:
    try:
        import psutil
        return psutil.virtual_memory().percent
    except ImportError:
        pass
    if os.name == "nt":
        class MemStatus(ctypes.Structure):
            _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong),
                        ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                        ("ptotal", ctypes.c_ulonglong), ("pavail", ctypes.c_ulonglong),
                        ("vtotal", ctypes.c_ulonglong), ("vavail", ctypes.c_ulonglong),
                        ("vext", ctypes.c_ulonglong)]
        st = MemStatus()
        st.length = ctypes.sizeof(st)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(st)):
            return 100.0 * (1 - st.avail / st.total)
        return None
    try:
        info = dict(line.split(":", 1) for line in open("/proc/meminfo"))
        total = int(info["MemTotal"].split()[0])
        avail = int(info["MemAvailable"].split()[0])
        return 100.0 * (1 - avail / total)
    except (OSError, KeyError, ValueError):
        return None


def _cpu_pct() -> float | None:
    try:
        import psutil
        return psutil.cpu_percent(interval=0.5)
    except ImportError:
        pass
    try:
        return min(100.0, 100.0 * os.getloadavg()[0] / (os.cpu_count() or 1))
    except (OSError, AttributeError):
        return None


def _uptime_s() -> float | None:
    try:
        import psutil
        return time.time() - psutil.boot_time()
    except ImportError:
        pass
    if os.name == "nt":
        return ctypes.windll.kernel32.GetTickCount64() / 1000.0
    try:
        return float(open("/proc/uptime").read().split()[0])
    except (OSError, ValueError):
        return None


def collect() -> list[tuple[str, float | None, str]]:
    """(label, percent or None, text) per row."""
    rows = []
    cpu = _cpu_pct()
    rows.append(("CPU", cpu, f"{cpu:.0f}%" if cpu is not None else "n/a"))
    mem = _mem_pct()
    rows.append(("RAM", mem, f"{mem:.0f}%" if mem is not None else "n/a"))
    root = os.path.abspath(os.sep)
    usage = shutil.disk_usage(root)
    disk = 100.0 * usage.used / usage.total
    rows.append(("DISK", disk, f"{disk:.0f}%  {usage.free / 2**30:.0f} GB free"))
    return rows


def render(rows=None, when: datetime | None = None) -> Image.Image:
    rows = rows if rows is not None else collect()
    image = Image.new("RGB", (WIDTH, HEIGHT), WHITE)
    d = ImageDraw.Draw(image)
    d.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=BLACK, width=2)

    d.rectangle([6, 6, WIDTH - 7, 30], fill=BLACK)
    d.text((WIDTH // 2, 18), "ShelfKit server", font=_font(15), fill=WHITE, anchor="mm")
    d.text((WIDTH // 2, 40), _fits(platform.node(), _font(13), WIDTH - 16), font=_font(13),
           fill=BLACK, anchor="ma")

    y = 66
    for label, pct, text in rows:
        d.text((10, y), label, font=_font(12), fill=BLACK)
        d.text((WIDTH - 10, y), text, font=_font(12), fill=RED if pct and pct >= WARN_PCT else BLACK,
               anchor="ra")
        bar = [10, y + 20, WIDTH - 11, y + 32]
        d.rectangle(bar, outline=BLACK, width=1)
        if pct is not None:
            fill_to = bar[0] + int((bar[2] - bar[0]) * min(pct, 100) / 100)
            d.rectangle([bar[0], bar[1], fill_to, bar[3]], fill=RED if pct >= WARN_PCT else BLACK)
        y += 50

    up = _uptime_s()
    if up is not None:
        days, rem = divmod(int(up), 86400)
        d.text((10, y + 4), f"up {days}d {rem // 3600}h {rem % 3600 // 60}m", font=_font(12), fill=BLACK)
    stamp = (when or datetime.now()).strftime("%Y-%m-%d %H:%M")
    d.text((WIDTH // 2, HEIGHT - 14), stamp, font=_font(10), fill=BLACK, anchor="mm")
    return image
