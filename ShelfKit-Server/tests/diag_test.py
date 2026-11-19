"""Diagnostics figures (shelfkit/diagstats.py) on a made-up fleet in a temporary database.

    python tests/diag_test.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from shelfkit import diagstats, store as store_mod  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


def main() -> int:
    # ── check-ins from poll times ────────────────────────────────────────────
    times = [i * 300.0 for i in range(0, 13)]                     # 0 .. 3600, every 5 min
    c = diagstats.checkins(times, 300, 0, 3600)
    check("a steady tag misses nothing", c["missed"] == 0 and c["heard"] == 13, c)
    gappy = [t for t in times if t not in (900.0, 1200.0)]       # two polls lost
    c = diagstats.checkins(gappy, 300, 0, 3600, keep_times=True)
    check("a gap of three intervals is two missed check-ins",
          c["missed"] == 2 and c["longest_gap_s"] == 900 and len(c["missed_at"]) == 2, c)
    tapped = sorted(times + [1505.0, 1510.0, 1507.0])            # quick polls after a tap
    c = diagstats.checkins(tapped, 300, 0, 3600)
    check("polls right after a tap count once", c["heard"] == 13 and c["missed"] == 0, c)
    c = diagstats.checkins(times[:5], 300, 0, 3600)               # silent after 1200 s
    check("a tag that went silent misses the rest", c["missed"] == 7, c)
    lost = [t for t in times if not 600 < t < 2400]               # an hour-long hole ...
    down = diagstats.offline(lost + [t + 7 for t in lost], 0, 3600, gap_s=900)
    c = diagstats.checkins(lost, 300, 0, 3600, down=down)
    check("a stretch nobody was listening counts neither way", c["missed"] == 0 and c["offline_s"] > 1000,
          (c, down))
    check("missed per hour lands in the right bucket",
          diagstats.hourly([3600 * 20 + 10], 86400.0) == [0] * 20 + [1] + [0] * 3)

    # ── a fleet in a database ────────────────────────────────────────────────
    tmp = Path(tempfile.mkdtemp())
    s = store_mod.Store(tmp / "d.db")
    now = time.time()
    since = now - 3 * 86400
    try:
        for n, (hex_id, drain_per_day) in enumerate((("0101", 0.002), ("0102", 0.002),
                                                      ("0103", 0.002), ("0104", 0.006))):
            s.touch_tag(hex_id, at=since - 10)
            for i in range(int(3 * 86400 / 300)):
                t = since + i * 300 + n
                if hex_id == "0102" and 500 < i < 510:
                    continue                                      # 9 lost polls (readings come in 1/256 V steps)
                fw = "1.1.0-49" if (hex_id != "0104" or i < 400) else "1.1.0-50"
                v = 3.02 - drain_per_day * (i * 300 / 86400)
                s.add_voltage(hex_id, round(v * 256), at=t, fw=fw)
        job = s.add_job("0101", "image", "weather.png", at=now - 3600)
        s.update_job(job, first_start_at=now - 3500, last_start_at=now - 3500,
                     ended_at=now - 3460, result="done", tries=1)
        failed = s.add_job("0102", "image", "pill.png", at=now - 1800)
        s.update_job(failed, result="failed", ended_at=now - 1700, tries=2, error="no answer")
        s.add_job("0102", "interval", "interval 600 s", at=now - 600)

        f = diagstats.fleet(s, since, now, 300)
        by = {t["hex_id"]: t for t in f["tags"]}
        check("every tag is in the fleet", sorted(by) == ["0101", "0102", "0103", "0104"], sorted(by))
        check("drain comes out in mV per day",
              abs(by["0101"]["drain"]["drain_mv_per_day"] - 2.0) < 0.2
              and abs(by["0104"]["drain"]["drain_mv_per_day"] - 6.0) < 0.3,
              (by["0101"]["drain"], by["0104"]["drain"]))
        check("the lost polls are counted as missed", by["0102"]["checkins"]["missed"] == 9,
              by["0102"]["checkins"])
        check("a steady tag misses none", by["0101"]["checkins"]["missed"] == 0, by["0101"]["checkins"])
        check("push timing: wait and transfer",
              by["0101"]["pushes"]["wait_s"] == 100 and by["0101"]["pushes"]["transfer_s"] == 40,
              by["0101"]["pushes"])
        check("a failed push is counted, an interval change is not a push",
              by["0102"]["pushes"]["failed"] == 1 and by["0102"]["pushes"]["queued"] == 1,
              by["0102"]["pushes"])
        fw = {g["version"]: g for g in f["firmware"]}
        check("both firmware versions are compared", sorted(fw) == ["1.1.0-49", "1.1.0-50"], sorted(fw))
        check("the newer firmware's drain is measured after it settled",
              fw["1.1.0-50"]["tags"] == ["0104"] and abs(fw["1.1.0-50"]["drain_mv_per_day"] - 6.0) < 0.4,
              fw["1.1.0-50"])
        check("the fleet median drain", abs(f["median_drain"] - 2.0) < 0.3, f["median_drain"])
        check("totals add up", f["totals"]["missed"] == 9 and f["totals"]["push_failed"] == 1,
              f["totals"])
        check("the last 24 hours come per hour", len(by["0101"]["day"]["hourly"]) == 24)

        b = diagstats.band(s, since, now, exclude="0104")
        check("the band leaves the tag itself out", b["tags"] == 3, b["tags"])
        mid = b["points"][-1]
        check("the band's median follows the fleet's drop",
              abs(mid[2] - (-0.002 * 3)) < 0.004, mid)

        t = diagstats.tag(s, "0102", 300)
        check("one tag's commands come newest first, with results",
              [j["result"] for j in t["jobs"]] == ["pending", "failed"], t["jobs"])
        check("one tag's day of check-ins", t["checkins"]["expected"] >= 280, t["checkins"])
    finally:
        s.close()
    print("\nALL PASS" if not FAILED else f"\nFAILED: {', '.join(FAILED)}")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
