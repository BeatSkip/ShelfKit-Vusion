"""Diagnostics figures: the whole fleet at once, and the extra panels of one tag.

Everything here is worked out from what the database already keeps:

    voltage   every poll carries the supply voltage, so its rows are also the tag's
              check-ins: a gap of two intervals is one missed check-in
    jobs      every queued command with when it was queued, started and finished,
              so a push's wait for the tag and its transfer time can be measured
    fw_reports which firmware each tag ran, to compare releases

Drain and current follow App.voltage_history(): a least-squares line through the
readings, and the CR2450 curve to turn its two ends into charge. A coin cell's
voltage is nearly flat for most of its life, so the current is a rough figure.
"""
from __future__ import annotations

import math
import threading
import time

CELL_MAH = 620.0
PUSH_KINDS = ("image", "service")       # the commands that put a picture on the glass
FW_SETTLE_S = 1800                      # the cell recovers for ~30 min after an update
MIN_SPAN_H = 6.0                        # shorter stretches give no useful drain figure
BAND_BUCKETS = 48
DOWN_GAP_S = 900                        # no tag heard for this long: the hub or server was off

_cache: dict = {}
_cache_lock = threading.Lock()
CACHE_S = 20.0


def _median(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    mid = len(values) // 2
    return values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2


def trend(points) -> dict | None:
    """Drain of a list of (time, volts): mV per day and µA, or None with too few readings."""
    from .app import battery_level

    if len(points) < 2:
        return None
    t0 = points[0][0]
    xs = [(p[0] - t0) / 86400.0 for p in points]
    vs = [p[1] for p in points]
    n = len(points)
    mx, mv = sum(xs) / n, sum(vs) / n
    var = sum((x - mx) ** 2 for x in xs)
    span_h = (points[-1][0] - t0) / 3600.0
    if var <= 0 or span_h <= 0:
        return None
    slope = sum((x - mx) * (v - mv) for x, v in zip(xs, vs)) / var       # V per day
    ua = None
    if span_h >= 1.0:
        used = battery_level(mv - slope * mx) - battery_level(mv + slope * (xs[-1] - mx))
        ua = round(max(0.0, used) / 100.0 * CELL_MAH * 1000.0 / span_h, 1)
    return {"drain_mv_per_day": round(-slope * 1000.0, 2), "ua": ua, "span_h": round(span_h, 2),
            "mean_v": round(mv, 3), "first_v": round(vs[0], 3), "last_v": round(vs[-1], 3)}


def offline(all_times, start: float, end: float, gap_s: float = DOWN_GAP_S) -> list:
    """Stretches in which no tag at all was heard: the server, the hub or its port was down,
    and nobody could have heard a tag. [(from, to)], from the merged poll times of every
    tag. With fewer than two tags a silent tag looks the same, so nothing is left out."""
    times = sorted(t for t in all_times if start <= t <= end)
    if not times:
        return [(start, end)]
    edges = [start] + times + [end]
    return [(a, b) for a, b in zip(edges, edges[1:]) if b - a > gap_s]


def _overlap(a: float, b: float, down) -> float:
    return sum(max(0.0, min(b, d1) - max(a, d0)) for d0, d1 in down)


def checkins(times, interval: float, start: float, end: float, keep_times: bool = False,
             down=()) -> dict:
    """How many check-ins a tag missed between start and end, from when it was heard.

    `down`: stretches nobody was listening (see offline()); they count neither as heard
    nor as missed.

    Polls closer together than half an interval (a retry, the quick polls after an NFC
    tap) count once. Inside a gap of g seconds round(g / interval) - 1 were missed; at the
    two ends of the window, where the neighbouring poll is not known, a check-in counts as
    missed only once it is half an interval overdue.
    """
    interval = max(5.0, float(interval))
    span = max(0.0, end - start)
    heard = []
    for t in times:
        if start <= t <= end and (not heard or t - heard[-1] >= interval * 0.5):
            heard.append(t)
    missed_at: list[float] = []
    missed = 0
    longest, longest_at = 0.0, None

    def gap(a: float, b: float, edge: bool) -> None:
        nonlocal missed, longest, longest_at
        g = b - a - _overlap(a, b, down)
        if g > longest:
            longest, longest_at = g, a
        m = max(0, math.floor(g / interval - 0.5)) if edge else max(0, round(g / interval) - 1)
        missed += m
        if keep_times and m:
            # where they were due: every interval after a, outside the offline stretches
            due = [a + interval * k for k in range(1, int((b - a) / interval) + 2)]
            due = [t for t in due if t < b and not any(d0 <= t < d1 for d0, d1 in down)]
            missed_at.extend(due[:min(m, 2000 - len(missed_at))])

    if not heard:
        gap(start, end, True)
    else:
        gap(start, heard[0], True)
        for a, b in zip(heard, heard[1:]):
            gap(a, b, False)
        gap(heard[-1], end, True)
    expected = len(heard) + missed
    out = {"interval_s": interval, "start": start, "end": end, "expected": expected,
           "offline_s": round(sum(max(0.0, min(end, d1) - max(start, d0)) for d0, d1 in down)),
           "heard": len(heard), "missed": missed,
           "heard_pct": round(100.0 * len(heard) / expected, 2) if expected else None,
           "longest_gap_s": round(longest), "longest_gap_at": longest_at,
           "span_h": round(span / 3600.0, 2)}
    if keep_times:
        out["missed_at"] = [round(t, 1) for t in missed_at[:2000]]
    return out


def hourly(missed_at, end: float, hours: int = 24) -> list[int]:
    """Missed check-ins per hour, oldest hour first, the last bucket ending at `end`."""
    buckets = [0] * hours
    for t in missed_at:
        back = int((end - t) // 3600)
        if 0 <= back < hours:
            buckets[hours - 1 - back] += 1
    return buckets


def _push_row(job: dict) -> dict:
    wait = (job["first_start_at"] - job["queued_at"]) if job.get("first_start_at") else None
    transfer = (job["ended_at"] - job["last_start_at"]
                if job.get("ended_at") and job.get("last_start_at") and job["result"] == "done"
                else None)
    return {"id": job["id"], "kind": job["kind"], "label": job["label"],
            "queued_at": job["queued_at"], "result": job["result"], "tries": job["tries"],
            "error": job["error"], "ended_at": job["ended_at"],
            "wait_s": None if wait is None else round(wait, 1),
            "transfer_s": None if transfer is None else round(transfer, 1)}


def _push_summary(jobs) -> dict:
    rows = [_push_row(j) for j in jobs if j["kind"] in PUSH_KINDS]
    done = [r for r in rows if r["result"] == "done"]
    return {"queued": len(rows), "delivered": len(done),
            "failed": sum(1 for r in rows if r["result"] == "failed"),
            "replaced": sum(1 for r in rows if r["result"] == "replaced"),
            "wait_s": _median(r["wait_s"] for r in done),
            "transfer_s": _median(r["transfer_s"] for r in done)}


def _cached(key, build):
    now = time.time()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and now - hit[0] < CACHE_S:
            return hit[1]
    value = build()
    with _cache_lock:
        if len(_cache) > 32:
            _cache.clear()
        _cache[key] = (now, value)
    return value


def fleet(store, since: float, until: float, poll_default: float, only=None) -> dict:
    """Every tag's figures over [since, until], firmware compared, and the last 24 hours'
    check-ins hour by hour. `only`: a set of tag ids to restrict it to (one shelf)."""
    only = frozenset(only) if only else None
    return _cached(("fleet", round(since / 60), round(until / 60), only),
                   lambda: _fleet(store, since, until, poll_default, only))


def _fleet(store, since: float, until: float, poll_default: float, only=None) -> dict:
    now = time.time()
    day0 = now - 86400.0
    readings = store.voltage_since(min(since, day0), max(until, now))
    heard_any = [t for rows in readings.values() for t, _v, _fw in rows]
    several = sum(1 for rows in readings.values() if rows) >= 2
    down = offline(heard_any, min(since, day0), max(until, now)) if several else []
    jobs = store.jobs_between(since, until)
    if only:
        jobs = [j for j in jobs if j["hex_id"] in only]
    first_seen = store.first_reports()
    tags_out = []
    versions: dict[str, dict] = {}
    for tag in store.tags():
        hex_id = tag["hex_id"]
        if only and hex_id not in only:
            continue
        interval = float(tag.get("poll_s") or poll_default)
        created = float(tag.get("created_at") or since)
        rows = [r for r in readings.get(hex_id, []) if since <= r[0] <= until]
        start = max(since, created)
        period = checkins([r[0] for r in rows], interval, start, until, down=down)
        last24 = checkins([r[0] for r in readings.get(hex_id, []) if r[0] >= day0],
                          interval, max(day0, created), now, keep_times=True, down=down)
        mine = [j for j in jobs if j["hex_id"] == hex_id]
        drain = trend([(t, v) for t, v, _fw in rows])
        if drain:
            drain["enough"] = drain["span_h"] >= MIN_SPAN_H
        tags_out.append({
            "hex_id": hex_id, "interval_s": interval,
            "readings": len(rows), "drain": drain,
            "checkins": period,
            "day": {"missed": last24["missed"], "expected": last24["expected"],
                    "hourly": hourly(last24["missed_at"], now)},
            "pushes": _push_summary(mine),
            "fw": rows[-1][2] if rows else None,
            "last_v": round(rows[-1][1], 3) if rows else None,
            "last_at": rows[-1][0] if rows else None,
        })
        # firmware: each stretch of one version, without the recovery after the update
        stretch: list = []
        for i, row in enumerate(rows + [None]):
            if row is not None and (not stretch or stretch[-1][2] == row[2]):
                stretch.append(row)
                continue
            if stretch and stretch[0][2]:
                version = stretch[0][2]
                begins_at_install = stretch[0] is not rows[0]
                body = [(t, v) for t, v, _fw in stretch
                        if not begins_at_install or t >= stretch[0][0] + FW_SETTLE_S]
                group = versions.setdefault(version, {"tags": set(), "drain": [], "ua": [],
                                                      "missed": 0, "expected": 0,
                                                      "pushes": [], "hours": 0.0})
                group["tags"].add(hex_id)
                t_end = row[0] if row is not None else until
                ci = checkins([r[0] for r in stretch], interval, stretch[0][0], t_end, down=down)
                group["missed"] += ci["missed"]
                group["expected"] += ci["expected"]
                group["pushes"] += [j for j in mine if stretch[0][0] <= j["queued_at"] < t_end]
                part = trend(body)
                if part and part["span_h"] >= MIN_SPAN_H:
                    group["drain"].append(part["drain_mv_per_day"])
                    group["ua"].append(part["ua"])
                    group["hours"] += part["span_h"]
            stretch = [row] if row is not None else []
    firmware = []
    for version, g in versions.items():
        pushes = _push_summary(g["pushes"])
        firmware.append({
            "version": version, "tags": sorted(g["tags"]),
            "drain_mv_per_day": _median(g["drain"]), "ua": _median(g["ua"]),
            "measured_h": round(g["hours"], 1), "measured_tags": len(g["drain"]),
            "missed": g["missed"], "expected": g["expected"],
            "pushes_failed": pushes["failed"], "pushes": pushes["queued"],
            "first_seen": first_seen.get(version),
        })
    firmware.sort(key=lambda f: f["first_seen"] or 0)
    totals = {
        "expected": sum(t["checkins"]["expected"] for t in tags_out),
        "missed": sum(t["checkins"]["missed"] for t in tags_out),
        "day_expected": sum(t["day"]["expected"] for t in tags_out),
        "day_missed": sum(t["day"]["missed"] for t in tags_out),
        **{f"push_{k}": v for k, v in _push_summary(jobs).items()},
    }
    drains = [t["drain"]["drain_mv_per_day"] for t in tags_out
              if t["drain"] and t["drain"]["span_h"] >= MIN_SPAN_H]
    uas = [t["drain"]["ua"] for t in tags_out
           if t["drain"] and t["drain"]["span_h"] >= MIN_SPAN_H]
    clip = lambda a, b: sum(max(0.0, min(b, d1) - max(a, d0)) for d0, d1 in down)  # noqa: E731
    return {"since": since, "until": until, "now": now, "tags": tags_out,
            "offline": [[round(a, 1), round(b, 1)] for a, b in down if b > since and a < until],
            "offline_s": round(clip(since, until)), "day_offline_s": round(clip(day0, now)),
            "firmware": firmware, "totals": totals,
            "median_drain": _median(drains), "median_ua": _median(uas)}


def band(store, since: float, until: float, exclude: str | None = None,
         buckets: int = BAND_BUCKETS) -> dict:
    """The fleet's normal voltage change over [since, until]: per time bucket the quartiles
    of every other tag's change since its own first bucket, in volts."""
    return _cached(("band", round(since / 60), round(until / 60), exclude, buckets),
                   lambda: _band(store, since, until, exclude, buckets))


def _band(store, since, until, exclude, buckets):
    width = max(60.0, (until - since) / buckets)
    per_tag = []
    for hex_id, rows in store.voltage_since(since, until).items():
        if hex_id == exclude or len(rows) < 4:
            continue
        sums = [[0.0, 0] for _ in range(buckets)]
        for t, v, _fw in rows:
            i = min(buckets - 1, int((t - since) // width))
            sums[i][0] += v
            sums[i][1] += 1
        means = [s / n if n else None for s, n in sums]
        base = next((m for m in means if m is not None), None)
        per_tag.append([None if m is None else m - base for m in means])
    points = []
    for i in range(buckets):
        vals = sorted(d[i] for d in per_tag if d[i] is not None)
        if len(vals) < 3:
            continue
        q = lambda f: vals[min(len(vals) - 1, max(0, round(f * (len(vals) - 1))))]  # noqa: E731
        points.append([round(since + (i + 0.5) * width, 1), round(q(0.25), 4),
                       round(_median(vals), 4), round(q(0.75), 4), len(vals)])
    return {"since": since, "until": until, "tags": len(per_tag), "points": points}


def tag(store, hex_id: str, poll_default: float) -> dict:
    """One tag's last 24 hours of check-ins, with the times of the missed ones, and its
    recent queued commands."""
    now = time.time()
    day0 = now - 86400.0
    info = next((t for t in store.tags() if t["hex_id"] == hex_id), None)
    interval = float((info or {}).get("poll_s") or poll_default)
    created = float((info or {}).get("created_at") or day0)
    times = [t for t, _v in store.voltage_between(hex_id, day0, now)]
    every = store.voltage_since(day0, now)
    down = []
    if sum(1 for rows in every.values() if rows) >= 2:
        down = offline([t for rows in every.values() for t, _v, _fw in rows], day0, now)
    day = checkins(times, interval, max(day0, created), now, keep_times=True, down=down)
    jobs = store.jobs_between(now - 30 * 86400.0, now, hex_id=hex_id, limit=40)
    return {"hex_id": hex_id, "now": now, "checkins": day,
            "offline": [[round(a, 1), round(b, 1)] for a, b in down],
            "jobs": [_push_row(j) for j in reversed(jobs)]}
