#!/usr/bin/env python3
"""Tests for InkServices (the mini-app platform), chunk by chunk.

    python ShelfKit-Server/tests/inkservices_test.py

No pytest, no hardware, same style as smoke.py. Exit code 0 = everything passed.
"""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVER))

from shelfkit import store as store_mod  # noqa: E402
from shelfkit.inkservices import appstore  # noqa: E402

FAILED: list[str] = []


def check(name: str, ok: bool, detail=None) -> None:
    if ok:
        print(f"  PASS {name}")
        return
    FAILED.append(name)
    print(f"  FAIL {name}" + (f"  <<< {detail}" if detail is not None else ""))


def test_store(tmp: Path) -> None:
    print("store (bindings)")
    s = store_mod.Store(tmp / "a.db")
    s.bind_app("0101", "hello")
    check("binding stored", (s.app_binding("0101") or {}).get("app_id") == "hello")
    s.set_app_pushed("0101", "abc", 1.0)
    check("push recorded", s.app_binding("0101")["last_hash"] == "abc")
    s.bind_app("0101", "other")
    check("rebind replaces app", s.app_binding("0101")["app_id"] == "other")
    check("rebind clears last_hash", s.app_binding("0101")["last_hash"] is None)
    check("bindings listed", [b["hex_id"] for b in s.app_bindings()] == ["0101"])

    s.rename_tag("0101", "0102")
    check("rename moves binding",
          s.app_binding("0102") is not None and s.app_binding("0101") is None)
    s.forget_tags(["0102"])
    check("forget drops binding", s.app_binding("0102") is None)

    s.bind_app("0201", "hello")
    s.unbind_app("0201")
    check("unbind", s.app_binding("0201") is None)
    s.close()

    # a version-4 database opens as version 5 with the new tables
    old = tmp / "v4.db"
    s = store_mod.Store(old)
    s.close()
    db = sqlite3.connect(str(old))
    db.execute("DROP TABLE IF EXISTS app_bindings")
    db.execute("PRAGMA user_version=4")
    db.commit()
    db.close()
    s = store_mod.Store(old)
    version = s._db.execute("PRAGMA user_version").fetchone()[0]
    check("migrates to 5", version == 5, version)
    s.bind_app("0301", "hello")
    check("migrated db takes bindings", s.app_binding("0301") is not None)
    s.close()


def test_appstore(tmp: Path) -> None:
    print("app store (one database per app)")
    path = appstore.app_db_path(tmp / "inkapps" / "pill")
    check("db sits in the app's data folder", path == tmp / "inkapps" / "pill" / "data" / "app.db")
    a = appstore.AppStore(path, "pill")
    a.set_config("0101", {"start": "2026-11-01"})
    a.set_state("0101", {"taken": [1, 2]})
    a.set_state("", {"shared": 1})
    check("per-tag config", a.config("0101") == {"start": "2026-11-01"})
    check("per-tag state", a.state("0101") == {"taken": [1, 2]})
    check("app-wide state", a.state("") == {"shared": 1})
    check("missing is {}", a.config("0999") == {} and a.state("0999") == {})
    check("tags with data", a.tags() == ["0101"])

    a.sql.execute("CREATE TABLE IF NOT EXISTS doses (hex_id TEXT, at REAL)")
    a.sql.execute("INSERT INTO doses VALUES ('0101', 1.5)")
    a.sql.commit()

    a.rename_tag("0101", "0102")
    check("rename moves config and state",
          a.config("0102") == {"start": "2026-11-01"} and a.state("0102") == {"taken": [1, 2]}
          and a.config("0101") == {})
    a.set_state("0103", {"x": 1})
    a.forget_tag("0103")
    check("forget drops the tag", a.state("0103") == {})
    a.forget_tag("")
    check("forget never drops shared data", a.state("") == {"shared": 1})
    a.close()

    # the folder is the app: a copy elsewhere opens with everything in it
    import shutil
    copy = tmp / "other-server" / "inkapps" / "pill"
    shutil.copytree(tmp / "inkapps" / "pill", copy)
    b = appstore.AppStore(appstore.app_db_path(copy), "pill")
    check("copied app keeps its data", b.state("0102") == {"taken": [1, 2]})
    check("copied app keeps its own tables",
          b.sql.execute("SELECT COUNT(*) FROM doses").fetchone()[0] == 1)
    b.close()

    # apps cannot open each other's database
    try:
        appstore.AppStore(path, "weather").close()
        check("another app's db refused", False)
    except appstore.AppStoreError:
        check("another app's db refused", True)


def test_displays(tmp: Path) -> None:
    print("display presets")
    from shelfkit import displays
    p = displays.preset(displays.DEFAULT_PRESET)
    check("default preset is the Vusion 2.6 BWR", p.id == "vusion-2.6-bwr")
    check("its size", (p.width, p.height) == (152, 296))
    check("its colours", p.colors == {"black": (0, 0, 0), "white": (255, 255, 255),
                                      "red": (255, 0, 0)})
    check("unknown preset falls back to the default",
          displays.preset("no-such-panel").id == displays.DEFAULT_PRESET)
    check("presets listed", [x["id"] for x in displays.presets()] == ["vusion-2.6-bwr"])


def test_sdk(tmp: Path) -> None:
    print("sdk")
    from shelfkit import displays
    from shelfkit.inkservices import BLACK, RED, Canvas, InkApp, TagContext

    a = InkApp("t1", title="T")

    @a.button("Press me")
    def _p(tag):
        pass

    check("button slug id", (a.action("press-me") or {}) and a.action("press-me").kind == "button")
    try:
        @a.button("Press me")
        def _p2(tag):
            pass
        check("duplicate action rejected", False)
    except ValueError:
        check("duplicate action rejected", True)

    @a.text_input("Message", placeholder="Say something")
    def _m(tag, text):
        pass

    check("text input", a.action("message").kind == "text"
          and a.action("message").placeholder == "Say something")
    a.config_field("greeting", label="Greeting", default="Hello")
    check("config field", a.config_fields[0].key == "greeting"
          and a.config_defaults() == {"greeting": "Hello"})

    @a.render
    def _r(tag, canvas):
        pass

    @a.on_open
    def _o(tag):
        pass

    check("render and on_open registered", a.render_fn is _r and a.on_open_fn is _o)

    c = Canvas()
    check("canvas defaults to the default preset", c.image.size == (152, 296)
          and c.display.id == displays.DEFAULT_PRESET)
    check("canvas exposes its size", (c.width, c.height) == (152, 296))
    y = c.text((4, 4), "x" * 200, size=14, max_width=60)
    beyond = c.image.crop((4 + 60 + 2, 0, c.width, 40)).getcolors()
    check("long text is cut at max_width", beyond is not None and len(beyond) == 1
          and beyond[0][1] == (255, 255, 255), beyond)
    check("text returns next y", y > 4)
    y2 = c.wrap((4, y), "word " * 60, size=12, max_lines=3)
    check("wrap stops at max_lines", y < y2 < y + 3 * 20)
    c.rect((0, 100, 20, 120), fill=RED)
    c.line([(0, 130), (151, 130)], color=BLACK)
    colours = {col for _, col in c.image.getcolors(1 << 16)}
    check("only panel colours", colours <= {(0, 0, 0), (255, 0, 0), (255, 255, 255)}, colours)

    # a canvas follows whatever preset it is given
    wide = displays.DisplayPreset("test-wide", "Test 400x300 BW", 400, 300,
                                  {"black": (0, 0, 0), "white": (255, 255, 255)})
    w = Canvas(wide)
    check("canvas takes the preset's size", w.image.size == (400, 300))
    try:
        w.rect((0, 0, 10, 10), fill=RED)
        check("colour the panel lacks is refused", False)
    except ValueError:
        check("colour the panel lacks is refused", True)

    t = TagContext(hex_id="0101", alias="A1", notes=None, config={}, data={}, shared={},
                   db=None, battery=3.0, display=displays.preset(displays.DEFAULT_PRESET))
    t.log("hello")
    check("tag context logs", t.logs and t.logs[-1][1] == "hello")
    check("tag context has a time", t.now is not None)

    @a.every(minutes=30)
    def tick(tag):
        pass

    check("timer registered", a.timers[0].id == "tick" and a.timers[0].minutes == 30
          and a.describe()["timers"] == [{"id": "tick", "minutes": 30.0}])
    try:
        a.every(minutes=0.1)
        check("timer faster than a minute refused", False)
    except ValueError:
        check("timer faster than a minute refused", True)
    seen = []
    t.fetch = lambda url, params, timeout: seen.append((url, params)) or {"ok": 1}
    check("fetch_json goes through the host's fetcher",
          t.fetch_json("https://x.test/a", {"q": 1}) == {"ok": 1}
          and seen == [("https://x.test/a", {"q": 1})])
    from shelfkit.inkservices.sdk import http_json
    try:
        http_json("file:///etc/passwd")
        check("fetch_json refuses non-http URLs", False)
    except ValueError:
        check("fetch_json refuses non-http URLs", True)


def write_app(root: Path, app_id: str, source: str) -> None:
    folder = root / app_id
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "app.py").write_text(source, encoding="utf-8")


def test_loader(tmp: Path) -> None:
    print("loader")
    from shelfkit.inkservices import loader
    root = tmp / "loader-apps"
    write_app(root, "good", "from shelfkit.inkservices import InkApp\napp = InkApp('good')\n")
    write_app(root, "broken", "def (\n")
    write_app(root, "noapp", "x = 1\n")
    write_app(root, "wrongid", "from shelfkit.inkservices import InkApp\napp = InkApp('other')\n")
    write_app(root, "raises", "raise RuntimeError('at import')\n")
    write_app(root, "_skipped", "raise SystemExit\n")
    (root / "notanapp").mkdir()

    apps = loader.load_apps(root)
    check("good app loads", apps["good"].app is not None and apps["good"].error is None)
    check("syntax error reported",
          apps["broken"].app is None and "SyntaxError" in (apps["broken"].error or ""),
          apps["broken"].error)
    check("missing app object reported",
          apps["noapp"].app is None and "app" in (apps["noapp"].error or ""))
    check("id must match the folder", apps["wrongid"].app is None
          and "other" in (apps["wrongid"].error or ""))
    check("import exception reported", "at import" in (apps["raises"].error or ""))
    check("_ folders and folders without app.py skipped",
          "_skipped" not in apps and "notanapp" not in apps)

    # a reload picks up an edited file
    write_app(root, "good", "from shelfkit.inkservices import InkApp\n"
                            "app = InkApp('good', title='Edited')\n")
    check("reload sees edits", loader.load_apps(root)["good"].app.title == "Edited")

    bundled = loader.load_apps()
    check("bundled hello loads", "hello" in bundled and bundled["hello"].error is None,
          bundled.get("hello") and bundled["hello"].error)


HOST_APPS = {
    "ctr": """
from shelfkit.inkservices import InkApp, RED
app = InkApp("ctr", title="Counter")
app.config_field("label", default="N")

@app.render
def draw(tag, canvas):
    canvas.text((4, 4), tag.config["label"], size=14)
    canvas.text((4, 30), str(tag.data.get("n", 0)), size=40, color=RED)

@app.button("Add")
def add(tag):
    tag.data["n"] = tag.data.get("n", 0) + 1
    tag.shared["total"] = tag.shared.get("total", 0) + 1

@app.text_input("Label")
def label(tag, text):
    tag.data["label"] = text

@app.button("Half")
def half(tag):
    tag.data["n"] = 99
    raise ValueError("half done")

@app.on_open
def opened(tag):
    tag.data["opened"] = tag.data.get("opened", 0) + 1
""",
    "bad": """
from shelfkit.inkservices import InkApp
app = InkApp("bad")

@app.render
def draw(tag, canvas):
    raise RuntimeError("boom")
""",
    "same": """
from shelfkit.inkservices import InkApp
app = InkApp("same")

@app.render
def draw(tag, canvas):
    canvas.rect((10, 10, 40, 40), fill="black")
""",
}


def test_host(tmp: Path) -> None:
    print("host")
    from shelfkit.inkservices.host import AppHost
    root = tmp / "host-apps"
    for app_id, source in HOST_APPS.items():
        write_app(root, app_id, source)
    s = store_mod.Store(tmp / "host.db")
    calls = []

    def enqueue(kind, addr, label, **params):
        calls.append((kind, addr, label, params))
        return {"ok": True, "queued": len(calls)}

    def info(hex_id):
        return {"alias": "A1", "notes": None, "battery": 3.0, "display": None}

    h = AppHost(s, enqueue=enqueue, tag_info=info, root=root, image_dir=tmp / "img")
    listed = {a["id"]: a for a in h.apps()}
    check("apps listed with controls", [c["id"] for c in listed["ctr"]["controls"]]
          == ["add", "label", "half"])

    r = h.bind("0101", "ctr", {"label": "Count"})
    check("bind pushes once", r.get("ok") and len(calls) == 1, r)
    check("push is an app image", calls[-1][0] == "image" and calls[-1][1] == 0x0101
          and calls[-1][3]["source"] == "app" and calls[-1][3]["dither"] == "threshold"
          and calls[-1][3]["fit"] == "stretch")
    check("bind stores config in the app's own db",
          h.store_of("ctr").config("0101") == {"label": "Count"})
    check("binding in the main store", s.app_binding("0101")["app_id"] == "ctr")

    r = h.refresh("0101")
    check("identical render is not pushed", r.get("skipped") == "identical" and len(calls) == 1, r)
    r = h.refresh("0101", force=True)
    check("forced refresh pushes", r.get("pushed") and len(calls) == 2, r)

    r = h.run_action("0101", "add")
    check("action changes the screen and pushes", r.get("ok") and r.get("pushed")
          and len(calls) == 3, r)
    check("action state persisted", h.store_of("ctr").state("0101").get("n") == 1)
    check("shared state persisted", h.store_of("ctr").state("") == {"total": 1})
    r = h.run_action("0101", "label", "hi")
    check("text action gets its value", h.store_of("ctr").state("0101").get("label") == "hi", r)
    check("unknown action refused", h.run_action("0101", "nope").get("ok") is False)
    check("actions are logged with what they did",
          any("action 'add': screen queued" in line for _, line in h.log("ctr")), h.log("ctr"))

    r = h.run_action("0101", "half")
    check("callback error reported", r.get("ok") is False and "half done" in r.get("error", ""), r)
    check("state saved even when the callback raised",
          h.store_of("ctr").state("0101").get("n") == 99)

    r = h.opened("0101")
    check("on_open runs", h.store_of("ctr").state("0101").get("opened") == 1, r)

    before = len(calls)
    h.bind("0102", "bad")
    r = h.refresh("0102", force=True)
    check("render error is contained", r.get("ok") is False and len(calls) == before, r)
    check("error in the app log", any("boom" in line for _, line in h.log("bad")))
    check("other tag still works", h.run_action("0101", "add").get("ok"))

    check("unbound tag", h.refresh("0999").get("ok") is False)
    check("bind unknown app", h.bind("0103", "missing").get("ok") is False)

    png = h.render_png("0101")
    check("render_png gives a PNG", png[:8] == b"\x89PNG\r\n\x1a\n")
    preview = h.preview_png("ctr", "0101")
    check("preview of an app on a tag", preview[:8] == b"\x89PNG\r\n\x1a\n")

    own = h.store_of("ctr").sql
    own.execute("CREATE TABLE IF NOT EXISTS history (at REAL, what TEXT)")
    own.executemany("INSERT INTO history VALUES (?, ?)", [(1, "a"), (2, "b")])
    own.commit()
    d = h.app_data("ctr")
    tags = {t["hex_id"]: t for t in d.get("tags", [])}
    check("app data: each tag's settings and data", d.get("ok") and "0101" in tags
          and tags["0101"]["config"].get("label") == "Count"
          and tags["0101"]["state"].get("opened") == 1 and tags["0101"]["bound"], d)
    check("app data: shared document", d.get("shared", {}).get("total", 0) >= 1, d.get("shared"))
    check("app data: the app's own tables with row counts",
          d.get("tables") == [{"name": "history", "rows": 2}], d.get("tables"))
    check("app data: where the file is", d.get("size", 0) > 0 and d["path"].endswith("app.db"), d)
    r = h.app_data("same")
    check("looking at an app that stored nothing creates no database",
          r.get("ok") and r["tags"] == [] and r["size"] == 0
          and not (root / "same" / "data").exists(), r)
    h.forget_tags(["0999"])
    h.rename_tag("0998", "0997")
    h.preview_png("same", "0101")
    check("forgetting, renaming or previewing creates no database in other apps",
          not (root / "same" / "data").exists())
    r = h.app_data("missing")
    check("app data of an unknown app", r.get("ok") is False
          and not (root / "missing").exists(), r)

    h.bind("0104", "same")
    before_rename = h.store_of("ctr").state("0101")
    h.rename_tag("0101", "0105")
    check("rename moves app data", before_rename.get("n") and
          h.store_of("ctr").state("0105") == before_rename
          and h.store_of("ctr").state("0101") == {})
    h.forget_tags(["0105"])
    check("forget drops app data", h.store_of("ctr").state("0105") == {}
          and h.store_of("ctr").state("") != {})

    h.unbind("0104")
    check("unbind", s.app_binding("0104") is None)
    h.close()
    s.close()


TIMER_APP = """
from shelfkit.inkservices import InkApp
app = InkApp("tick", title="Tick")

@app.render
def draw(tag, canvas):
    canvas.text((4, 4), str(tag.data.get("shown", 0)), size=40)

@app.every(minutes=10)
def count(tag):
    tag.data["ticks"] = tag.data.get("ticks", 0) + 1
    if tag.config.get("change") == "yes":
        tag.data["shown"] = tag.data["ticks"]

@app.every(minutes=60)
def fetch(tag):
    tag.data["got"] = tag.fetch_json("https://x.test/w", {"tag": tag.hex_id})
"""

BAD_TIMER_APP = """
from shelfkit.inkservices import InkApp
app = InkApp("badtick")

@app.render
def draw(tag, canvas):
    pass

@app.every(minutes=5)
def boom(tag):
    tag.data["tries"] = tag.data.get("tries", 0) + 1
    raise RuntimeError("network down")
"""


def test_timers(tmp: Path) -> None:
    print("timers (@app.every)")
    from datetime import datetime

    from shelfkit.inkservices.host import AppHost
    root = tmp / "timer-apps"
    write_app(root, "tick", TIMER_APP)
    write_app(root, "badtick", BAD_TIMER_APP)
    s = store_mod.Store(tmp / "timers.db")
    calls, fetched = [], []
    clock = [datetime(2026, 11, 12, 8, 0)]
    h = AppHost(s, enqueue=lambda *a, **k: calls.append(a) or {"ok": True},
                tag_info=lambda hx: {}, root=root, image_dir=tmp / "timer-img",
                fetch=lambda url, params, timeout: fetched.append(params) or {"t": 1},
                clock=lambda: clock[0])
    st = h.store_of("tick")
    check("timers listed", [t["id"] for t in h.apps()[[a["id"] for a in h.apps()].index("tick")]
                            ["timers"]] == ["count", "fetch"])

    r = h.bind("0101", "tick")
    check("timers run once when the app is put on a tag",
          r.get("ok") and st.state("0101").get("ticks") == 1
          and st.state("0101").get("got") == {"t": 1} and fetched == [{"tag": "0101"}], r)
    check("...and the tag gets one push", len(calls) == 1, calls)

    t0 = 1000.0
    check("first scheduler pass only learns the timers", h.run_due(t0) == 0)
    check("nothing due before its time", h.run_due(t0 + 9 * 60) == 0
          and st.state("0101").get("ticks") == 1)
    n = h.run_due(t0 + 10 * 60)
    check("a timer runs when due", n == 1 and st.state("0101").get("ticks") == 2, n)
    check("an unchanged screen is not pushed", len(calls) == 1, calls)
    check("an unchanged timer run is not logged",
          not any("count" in line for _, line in h.log("tick")), h.log("tick"))

    h.set_config("0101", {"change": "yes"})
    pushes = len(calls)
    h.run_due(t0 + 20 * 60)
    check("a timer that changes the screen pushes it", len(calls) == pushes + 1
          and any("timer count: screen queued" in line for _, line in h.log("tick")),
          h.log("tick"))
    h.run_due(t0 + 60 * 60)
    check("the hourly timer runs on its own beat", len(fetched) == 2, fetched)

    clock[0] = datetime(2026, 11, 12, 9, 0)
    h.bind("0102", "badtick")
    bst = h.store_of("badtick")
    tries = bst.state("0102").get("tries")
    h.run_due(t0 + 61 * 60)              # learns the new tag's timer: due in 5 min
    h.run_due(t0 + 66 * 60)
    h.run_due(t0 + 66 * 60 + 1)
    check("a failing timer is retried at its interval, not in a loop",
          bst.state("0102").get("tries") == tries + 1, (tries, bst.state("0102")))
    check("timer failure is logged", any("network down" in line for _, line in h.log("badtick")))

    h.unbind("0101")
    before = st.state("0101").get("ticks")
    h.run_due(t0 + 999 * 60)
    check("a tag without the app gets no timer runs", st.state("0101").get("ticks") == before)

    before = len(fetched)
    h.bind("0103", "tick")
    r = h.update_now("0103")
    check("update now runs the timers at once", len(fetched) == before + 2 and r.get("ok"), r)

    h.start_scheduler(interval=0.05)
    h.close()
    check("close stops the scheduler", h._scheduler is None or not h._scheduler.is_alive())
    s.close()


FORECAST = {   # the shape Open-Meteo answers with (trimmed)
    "current": {"time": "2026-11-12T08:30", "temperature_2m": 7.6, "weather_code": 61,
                "wind_speed_10m": 18.4, "is_day": 1},
    "daily": {"time": ["2026-11-12", "2026-11-13", "2026-11-14", "2026-11-15"],
              "weather_code": [61, 3, 0, 80],
              "temperature_2m_max": [9.1, 10.4, 12.0, 8.2],
              "temperature_2m_min": [4.2, 5.0, 3.1, 2.9]},
}


def _reference_host(tmp: Path, name: str, clock, fetch=None):
    """The real apps from inkapps/, copied so a test run never writes into their data/."""
    import shutil

    from shelfkit.inkservices.host import AppHost
    from shelfkit.inkservices.loader import INKAPPS_DIR
    root = tmp / name
    for app_id in ("pill", "weather"):
        shutil.copytree(INKAPPS_DIR / app_id, root / app_id,
                        ignore=shutil.ignore_patterns("data", "__pycache__"))
    s = store_mod.Store(tmp / f"{name}.db")
    calls = []
    h = AppHost(s, enqueue=lambda *a, **k: calls.append(a) or {"ok": True},
                tag_info=lambda hx: {"alias": "Bathroom"}, root=root,
                image_dir=tmp / f"{name}-img", clock=lambda: clock[0],
                fetch=fetch or (lambda *a: (_ for _ in ()).throw(OSError("offline"))))
    return h, s, calls


def _layout_noise(h, app_id) -> list:
    return [line for _, line in h.log(app_id) if "layout warn" in line or "layout error" in line
            or "failed" in line]


def test_pill_app(tmp: Path) -> None:
    print("reference app: pill tracker")
    from datetime import datetime
    clock = [datetime(2026, 11, 12, 7, 55)]
    h, s, calls = _reference_host(tmp, "pill-apps", clock)
    check("pill app loads", h.loaded["pill"].error is None, h.loaded["pill"].error)
    app = h.loaded["pill"].app
    check("pill app redraws on a timer", app.timers and app.timers[0].minutes <= 30)
    st = h.store_of("pill")

    r = h.bind("0101", "pill", {"remind_at": "20:00"})
    check("bind draws without layout problems", r.get("ok") and not _layout_noise(h, "pill"),
          (r, _layout_noise(h, "pill")))
    d = app.data_fn(h._context(app, "0101"))
    check("not taken yet, before the reminder", d["status"] == "due", d["status"])
    days = [c for c in d["cells"] if c["n"]]
    check("a cell per day of the month", len(days) == 30
          and len(d["cells"]) % 7 == 0, len(days))
    check("november 2026 starts on a sunday (monday-first grid)",
          d["cells"][6]["n"] == 1 and not d["cells"][5]["n"])

    clock[0] = datetime(2026, 11, 12, 8, 2)
    r = h.opened("0101")
    check("an NFC tap logs the pill", r.get("ok") and r.get("pushed")
          and st.state("0101")["taken"] == ["2026-11-12T08:02"], (r, st.state("0101")))
    clock[0] = datetime(2026, 11, 12, 8, 4)
    h.opened("0101")
    check("a second tap the same day logs nothing", st.state("0101")["taken"] == ["2026-11-12T08:02"])
    d = app.data_fn(h._context(app, "0101"))
    today = next(c for c in d["cells"] if c["n"] == 12)
    check("today shows as taken", d["status"] == "taken" and today["bg"] == "black", today)
    check("last taken date and time", d["last_time"] == "08:02" and "12" in d["last_date"], d)
    check("no layout problems after a tap", not _layout_noise(h, "pill"), _layout_noise(h, "pill"))

    clock[0] = datetime(2026, 11, 13, 20, 30)
    d = app.data_fn(h._context(app, "0101"))
    check("after the reminder time an untaken pill is late", d["status"] == "late", d["status"])
    r = h.update_now("0101")
    check("the late screen renders cleanly", r.get("ok") and not _layout_noise(h, "pill"),
          (r, _layout_noise(h, "pill")))
    clock[0] = datetime(2026, 11, 15, 9, 0)
    d = app.data_fn(h._context(app, "0101"))
    missed = [c["n"] for c in d["cells"] if c.get("missed")]
    check("days without a pill since tracking began are marked missed",
          missed == [13, 14], missed)
    check("days before tracking began are not missed", 11 not in missed)
    cells = {c["n"]: c for c in d["cells"] if c["n"]}
    check("every taken day is solid black with a white number",
          all(c["bg"] == "black" and c["fg"] == "white" for c in cells.values() if c["taken"])
          and cells[12]["taken"], cells[12])
    check("missed days are solid red", all(cells[n]["bg"] == "red" for n in (13, 14)))
    check("days still to come stay quiet", cells[20]["bg"] == "white"
          and cells[20]["border"] == "none")
    check("the month's tally", d["taken_count"] == 1 and d["missed_count"] == 2,
          (d["taken_count"], d["missed_count"]))

    h.run_action("0101", "undo")
    check("undo removes the last pill", st.state("0101")["taken"] == [])

    h.set_config("0101", {"pack_start": "2026-11-01", "break_days": "7"})
    d = app.data_fn(h._context(app, "0101"))
    brk = [c["n"] for c in d["cells"] if c.get("brk")]
    check("a 21+7 pack marks the pill-free week", brk == [22, 23, 24, 25, 26, 27, 28], brk)
    check("pill-free days are dotted and carry no number (no text on a pattern)",
          all(c["bg"] == "dots" and not c["show"] for c in d["cells"] if c.get("brk")))
    clock[0] = datetime(2026, 11, 23, 21, 0)
    d = app.data_fn(h._context(app, "0101"))
    check("a pill-free day is never late", d["status"] == "break", d["status"])
    h.update_now("0101")
    check("pill-free week renders cleanly", not _layout_noise(h, "pill"), _layout_noise(h, "pill"))

    h.set_config("0101", {"remind_at": "25:99", "pack_start": "soon", "break_days": "x"})
    r = h.update_now("0101")
    check("nonsense settings do not break the app", r.get("ok"), r)
    h.close()
    s.close()


def test_weather_app(tmp: Path) -> None:
    print("reference app: weather and moon")
    from datetime import datetime, timezone
    clock = [datetime(2026, 11, 12, 8, 30)]
    fetched = []

    def fetch(url, params, timeout):
        fetched.append((url, params))
        return FORECAST

    h, s, calls = _reference_host(tmp, "wx-apps", clock, fetch)
    check("weather app loads", h.loaded["weather"].error is None, h.loaded["weather"].error)
    app = h.loaded["weather"].app
    st = h.store_of("weather")

    r = h.bind("0201", "weather")
    check("without a place it asks for one and fetches nothing",
          r.get("ok") and fetched == [] and app.data_fn(h._context(app, "0201")).get("setup"), r)
    check("setup screen renders cleanly", not _layout_noise(h, "weather"), _layout_noise(h, "weather"))

    r = h.bind("0202", "weather", {"place": "Utrecht", "latitude": "52.09",
                                   "longitude": "5.12"})
    check("bind fetches the forecast once", r.get("ok") and len(fetched) == 1, (r, fetched))
    url, params = fetched[0]
    check("asks Open-Meteo for this place", "open-meteo.com" in url
          and params["latitude"] == 52.09 and params["longitude"] == 5.12, fetched[0])
    d = app.data_fn(h._context(app, "0202"))
    check("current weather", d["temp"] == 8 and d["icon"] == "rain" and d["wind"] == 18, d)
    check("three days ahead", [x["day"] for x in d["days"]] == ["Today", "Fri", "Sat"]
          and d["days"][1]["hi"] == 10 and d["days"][2]["icon"] == "sun", d["days"])
    check("weather screen renders cleanly", not _layout_noise(h, "weather"),
          _layout_noise(h, "weather"))

    h.bind("0203", "weather", {"place": "Utrecht", "latitude": "52.09", "longitude": "5.12"})
    check("a second tag at the same place uses the cached forecast", len(fetched) == 1, fetched)
    clock[0] = datetime(2026, 11, 12, 9, 10)
    h.update_now("0203")
    check("the cache expires", len(fetched) == 2, fetched)

    clock[0] = datetime(2026, 11, 12, 13, 0)
    h.fetch = lambda *a: (_ for _ in ()).throw(OSError("offline"))
    r = h.update_now("0202")
    d = app.data_fn(h._context(app, "0202"))
    check("offline keeps the last forecast and says how old it is",
          d["temp"] == 8 and "09:10" in d.get("stale", ""), d.get("stale"))
    check("stale screen renders cleanly", r.get("ok") or "offline" in str(r))

    def moon_at(when):
        clock[0] = when
        return app.data_fn(h._context(app, "0202"))["moon"]

    full = moon_at(datetime(2024, 1, 25, 18, 0, tzinfo=timezone.utc))
    new = moon_at(datetime(2024, 1, 11, 12, 0, tzinfo=timezone.utc))
    check("moon phase: full", full["name"] == "Full moon" and full["lit"] >= 99, full)
    check("moon phase: new", new["name"] == "New moon" and new["lit"] <= 1, new)

    h.set_config("0202", {"place": "X", "latitude": "north", "longitude": "5"})
    d = app.data_fn(h._context(app, "0202"))
    check("a bad latitude asks for numbers", d.get("setup") and "number" in d.get("why", ""), d)
    h.close()
    s.close()


def test_layout_apps(tmp: Path) -> None:
    print("apps drawn with an InkLayout")
    from shelfkit.inkservices.host import AppHost
    root = tmp / "layout-apps"
    write_app(root, "lay", """
from shelfkit.inkservices import InkApp
app = InkApp("lay", layout="layout.xml")

@app.data
def data(tag):
    return {"n": tag.data.get("n", 0), "who": tag.alias}

@app.button("Add")
def add(tag):
    tag.data["n"] = tag.data.get("n", 0) + 1
""")
    (root / "lay" / "layout.xml").write_text(
        '<screen><text size="24">{{ data.who }}: {{ data.n }}</text>'
        '<text>{{ data.nothing }}</text></screen>', encoding="utf-8")
    write_app(root, "badlay", """
from shelfkit.inkservices import InkApp
app = InkApp("badlay", layout="layout.xml")
""")
    (root / "badlay" / "layout.xml").write_text("<screen><txt>x</txt></screen>",
                                                encoding="utf-8")
    write_app(root, "nolay", """
from shelfkit.inkservices import InkApp
app = InkApp("nolay", layout="missing.xml")
""")

    s = store_mod.Store(tmp / "lay.db")
    calls = []
    h = AppHost(s, enqueue=lambda *a, **k: calls.append(a) or {"ok": True},
                tag_info=lambda hx: {"alias": "Shelf"}, root=root, image_dir=tmp / "lay-img")
    check("layout app loads", h.loaded["lay"].error is None, h.loaded["lay"].error)
    r = h.bind("0101", "lay")
    check("layout app pushes", r.get("ok") and len(calls) == 1, r)
    result = h.layout_result("0101")
    check("data function feeds the layout", "Shelf: 0" in result.boxes, result.boxes)
    h.run_action("0101", "add")
    check("action re-renders the layout", "Shelf: 1" in h.layout_result("0101").boxes)
    check("layout warnings go to the app log",
          any("data.nothing" in line for _, line in h.log("lay")), h.log("lay"))

    r = h.bind("0102", "badlay")
    check("layout errors stop the push", r.get("ok") is False and len(calls) == 2
          and "txt" in r.get("error", ""), r)
    r = h.bind("0103", "nolay")
    check("missing layout file is reported", r.get("ok") is False
          and "missing.xml" in r.get("error", ""), r)
    h.close()
    s.close()


def test_wiring(tmp: Path) -> None:
    print("server wiring")
    import subprocess

    from PIL import Image

    from shelfkit.app import App
    from shelfkit.serial_link import PortSpec

    png = tmp / "plain.png"
    Image.new("RGB", (152, 296), "white").save(png)
    s = store_mod.Store(tmp / "wiring.db")
    a = App([PortSpec("hub", "INKTEST")], False, store=s)    # a hub port, never opened
    try:
        a.enqueue("image", 0x0101, "app x", path=str(png), source="app")
        a.enqueue("image", 0x0101, "app x", path=str(png), source="app")
        a.enqueue("image", 0x0101, "manual", path=str(png))
        a.enqueue("image", 0x0102, "app x", path=str(png), source="app")
        pending = [j for j in a.queue if j["state"] == "pending"]
        mine = [j for j in pending if j["addr"] == 0x0101]
        check("app pushes supersede each other", len(mine) == 2, [j["label"] for j in mine])
        check("manual push untouched", any(j["label"] == "manual" for j in mine))
        check("other tags untouched", any(j["addr"] == 0x0102 for j in pending))

        root = tmp / "wiring-apps"
        write_app(root, "ctr", HOST_APPS["ctr"])
        host = a.start_inkservices(root=root, image_dir=tmp / "wiring-img")
        check("App has an inkhost", a.inkhost is host)
        a.tag_meta[0x0101] = {"alias": "Shelf 1", "notes": "n"}
        info = a.ink_tag_info("0101")
        check("tag info from the App", info["alias"] == "Shelf 1" and "display" in info, info)
        r = host.bind("0101", "ctr")
        check("binding through the App queues an image", r.get("ok") and any(
            j["label"] == "app ctr" for j in a.queue if j["addr"] == 0x0101), r)

        host.run_action("0101", "add")
        a.tags[0x0101] = 1
        a._rename_tag(0x0101, 0x0105)
        check("tag rename reaches the app's data",
              host.store_of("ctr").state("0105").get("n") == 1)
        a.tags[0x0105] = 1
        a.forget_tags(["0105"])
        check("forgetting a tag reaches the app's data",
              host.store_of("ctr").state("0105") == {})
    finally:
        if a.inkhost:
            a.inkhost.close()
        s.close()

    out = tmp / "h.png"
    run = subprocess.run([sys.executable, "-m", "shelfkit.inkservices", "render", "hello",
                          "--out", str(out)], cwd=SERVER, capture_output=True, text=True)
    check("render CLI", run.returncode == 0 and out.is_file()
          and Image.open(out).size == (152, 296), run.stderr[-300:])


def test_web(tmp: Path) -> None:
    print("http routes")
    import base64
    import json
    import threading
    import urllib.error
    import urllib.request

    from shelfkit import webapp
    from shelfkit.app import App
    from shelfkit.serial_link import PortSpec

    s = store_mod.Store(tmp / "web.db")
    a = App([PortSpec("hub", "INKWEB")], False, store=s)
    root = tmp / "web-apps"
    write_app(root, "ctr", HOST_APPS["ctr"])
    a.start_inkservices(root=root, image_dir=tmp / "web-img")
    server = webapp.make_server(a, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    base = f"http://127.0.0.1:{server.server_address[1]}"

    def get(path):
        with urllib.request.urlopen(base + path, timeout=10) as res:
            return res.status, res.headers.get("Content-Type"), res.read()

    def post(path, body):
        req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=10) as res:
                return json.loads(res.read())
        except urllib.error.HTTPError as exc:
            return json.loads(exc.read())

    try:
        status, _, body = get("/inkapps.html")
        check("development page served", status == 200 and b"Layout playground" in body)
        listing = json.loads(get("/api/inkapps")[2])
        check("apps listed", [x["id"] for x in listing["apps"]] == ["ctr"], listing)
        status, ctype, png = get("/api/inkapps/preview.png?app=ctr&tag=0101")
        check("preview png", ctype == "image/png" and png[:4] == b"\x89PNG")
        r = post("/api/inkapps/bind", {"tag": "0101", "app": "ctr"})
        check("bind over http", r.get("ok"), r)
        r = post("/api/inkapps/action", {"tag": "0101", "action": "add"})
        check("action over http", r.get("ok") and r.get("pushed"), r)
        r = post("/api/inkapps/action", {"tag": "zz", "action": "add"})
        check("bad tag refused", "hex" in r.get("error", ""), r)
        r = post("/api/layout/render", {"layout": "<screen><text>Hi</text></screen>"})
        check("layout render over http", r.get("ok") and r["size"] == [152, 296]
              and base64.b64decode(r["png"])[:4] == b"\x89PNG" and "Hi" in r["boxes"], r)
        r = post("/api/layout/render", {"layout": "<screen><nope/></screen>"})
        check("layout errors come back as diagnostics", r.get("ok") is False
              and r["diagnostics"][0]["level"] == "error", r)
        displays_ = json.loads(get("/api/layout/displays")[2])
        check("display presets over http", displays_["default"] == "vusion-2.6-bwr")
        data = json.loads(get("/api/inkapps/data?app=ctr")[2])
        check("app data over http", data.get("ok") and data["tags"][0]["hex_id"] == "0101"
              and data["tags"][0]["state"].get("n") == 1, data)
        status, _, body = get("/")
        check("main page has the Apps screen", b'data-screen="apps"' in body
              and b"/apps.js" in body)
        status, ctype, body = get("/apps.js")
        check("apps.js served", status == 200 and "javascript" in ctype and b"renderApps" in body)
        status, ctype, body = get("/api/layout/skill")
        check("skill file over http", "markdown" in ctype and body.startswith(b"---\nname: "))
    finally:
        server.shutdown()
        server.server_close()
        a.inkhost.close()
        s.close()


def test_phone(tmp: Path) -> None:
    print("tag pages (what an NFC tap opens), on the main server")
    import http.client
    import json
    import threading
    import urllib.parse

    from shelfkit import webapp
    from shelfkit.app import App
    from shelfkit.serial_link import PortSpec

    s = store_mod.Store(tmp / "phone.db")
    a = App([PortSpec("hub", "INKPHONE")], False, store=s)
    root = tmp / "phone-apps"
    write_app(root, "ctr", HOST_APPS["ctr"])
    host = a.start_inkservices(root=root, image_dir=tmp / "phone-img")
    a.tag_meta[0x0101] = {"alias": "Pill strip"}
    server = webapp.make_server(a, "127.0.0.1", 0)
    threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05},
                     daemon=True).start()
    port = server.server_address[1]

    def req(method, path, body=None, headers=None, raw=False):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
        hdrs = {"Host": f"127.0.0.1:{port}", **(headers or {})}
        if body is not None:
            body = urllib.parse.urlencode(body)
            hdrs["Content-Type"] = "application/x-www-form-urlencoded"
        conn.request(method, path, body=body, headers=hdrs)
        res = conn.getresponse()
        out = (res.status, res.getheader("Location"), res.getheader("Content-Type"), res.read())
        headers_ = dict(res.getheaders())
        conn.close()
        return (out, headers_) if raw else out

    def state():
        return host.store_of("ctr").state("0101")

    try:
        status, loc, _, _ = req("GET", "/tag/0101")
        check("links are relative, so a proxy may mount them anywhere",
              status == 303 and loc == "0101/view", (status, loc))
        status, _, _, body = req("GET", "/tag/0101/view")
        check("unbound tag gets a friendly page", status == 200 and b"no app" in body.lower()
              and b"0101" in body, body[:200])

        host.bind("0101", "ctr")
        status, loc, _, _ = req("GET", "/tag/0101")
        check("opening the tag's link runs on_open, then redirects",
              status == 303 and (loc or "").startswith("0101/view")
              and state().get("opened") == 1, (status, loc))
        status, loc, _, _ = req("GET", "/tag/0101/")
        check("a trailing slash works too", status == 303 and (loc or "").startswith("view"), loc)
        check("a second open within the debounce counts once", state().get("opened") == 1)

        (status, _, _, body), hdrs = req("GET", "/tag/0101/view", raw=True)
        page = body.decode()
        check("view page shows the app and its controls", status == 200
              and "Counter" in page and 'value="add"' in page and "Pill strip" in page
              and 'name="value"' in page, page[:300])
        check("view page needs no script", "<script" not in page)
        check("view page uses relative links only", 'action="do"' in page
              and "src='screen.png" in page and "/tag/" not in page, page[:600])
        csp = hdrs.get("Content-Security-Policy", "")
        check("view page is locked down", "script-src" not in csp and "default-src 'none'" in csp
              and "form-action 'self'" in csp and "frame-ancestors 'none'" in csp, csp)
        check("referrer policy keeps the form's Origin",
              hdrs.get("Referrer-Policy", "").lower() not in ("", "no-referrer"), hdrs)

        status, loc, _, _ = req("POST", "/tag/0101/do", {"action": "add"})
        check("a button press runs the action and redirects back",
              status == 303 and (loc or "").startswith("view?") and state().get("n") == 1,
              (status, loc))
        req("POST", "/tag/0101/do", {"action": "label", "value": "Hi there"})
        check("text is passed to the action", state().get("label") == "Hi there")
        status, _, _, body = req("GET", "/tag/0101/" + loc)
        check("the result is shown after the redirect", status == 200 and b"next check-in" in body,
              body[:400])
        status, _, ctype, png = req("GET", "/tag/0101/screen.png")
        check("current screen as png", status == 200 and png[1:4] == b"PNG")

        status, _, _, _ = req("POST", "/tag/0101/do", {"action": "add"},
                              {"Origin": "http://evil.example"})
        check("cross-site post refused", status == 403 and state().get("n") == 1)
        status, _, _, _ = req("POST", "/tag/0101/do", {"action": "add"},
                              {"Origin": f"http://127.0.0.1:{port}"})
        check("the page's own post is accepted", status == 303 and state().get("n") == 2, status)
        status, _, _, _ = req("POST", "/tag/0101/do", {"action": "add"},
                              {"Origin": "https://shelf.example.org",
                               "X-Forwarded-Host": "shelf.example.org"})
        check("a post through a reverse proxy is accepted", status == 303
              and state().get("n") == 3, status)

        status, loc, _, _ = req("GET", "/t/0101")
        check("old /t/ links still work", status == 301 and loc == "../tag/0101", (status, loc))
        status, loc, _, _ = req("GET", "/t/0101/view")
        check("old /t/ links keep their page", loc == "../../tag/0101/view", loc)
        for path in ("/tag/zzzz", "/tag/0101/x", "/tag/0101/view/x", "/tag/"):
            status, _, _, _ = req("GET", path)
            check(f"{path} is not a tag page", status == 404, status)
        status, _, _, _ = req("POST", "/tag/0101/view", {"action": "add"})
        check("only /do takes a post", status in (404, 405) and state().get("n") == 3, status)

        listing = json.loads(req("GET", "/api/inkapps")[3])
        check("the admin side is on the same server", listing["apps"][0]["id"] == "ctr")
        check("without a public address the links point at this server",
              listing["phone_base"].startswith("http://") and listing.get("phone_base_local"),
              listing.get("phone_base"))
        r = a.set_prefs({"public_url": "https://shelf.example.org/home/"})
        listing = json.loads(req("GET", "/api/inkapps")[3])
        check("the public address from Settings is used for the links",
              listing["phone_base"] == "https://shelf.example.org/home"
              and not listing.get("phone_base_local"), (r, listing.get("phone_base")))
        r = a.set_prefs({"public_url": "javascript:alert(1)"})
        check("a public address must be an http(s) URL",
              a.prefs["public_url"] == "https://shelf.example.org/home", (r, a.prefs))
    finally:
        server.shutdown()
        server.server_close()
        host.close()
        s.close()


def main() -> int:
    # a failed test can leave a database open, which Windows will not delete
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
        tmp = Path(d)
        for test in (test_store, test_appstore, test_displays, test_sdk, test_loader,
                     test_host, test_timers, test_pill_app, test_weather_app, test_layout_apps,
                     test_wiring, test_web,
                     test_phone):
            try:
                test(tmp)
            except Exception as exc:  # noqa: BLE001 - report and keep going
                check(f"{test.__name__} ran", False, f"{type(exc).__name__}: {exc}")
    print("FAILED: " + ", ".join(FAILED) if FAILED else "ALL PASS")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
