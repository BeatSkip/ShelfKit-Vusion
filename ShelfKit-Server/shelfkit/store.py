"""Durable state for the server: one SQLite file, no ORM.

Everything the server would otherwise forget on restart lives here — the editor's
image and render options, the port each pane was using, what each tag was last
seen doing and last sent, the rendered bitmaps themselves (so thumbnails and
previews survive a bounce), and an append-only event log that backs the Logs
screen.

One connection, guarded by a lock: the app calls in from HTTP threads, the
per-pane reader threads and the image-push thread. SQLite in WAL mode handles
that fine at this scale, and a lock keeps it simple enough to reason about.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA_VERSION = 6
MAX_EVENTS = 5000      # keep the newest N; the Logs screen never shows more
MAX_BITMAPS = 64       # content store ceiling (each row ~15 KB of blobs)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,          -- JSON
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS tags (
    hex_id      TEXT PRIMARY KEY,      -- '0100', 4 uppercase hex, no prefix
    alias       TEXT,
    notes       TEXT,
    grid_row    INTEGER,               -- fleet-map position, both null until set
    grid_col    INTEGER,
    last_seen   REAL,                  -- unix time of the last POLL
    seen_count  INTEGER NOT NULL DEFAULT 0,
    last_status TEXT,
    battery     INTEGER,
    push_name   TEXT,                  -- last content pushed to this tag
    push_key    TEXT,                  -- the bitmap it was rendered into
    push_at     REAL,
    fw_version  TEXT,                  -- '0.0.1', from the tag's last NFC-tapped poll
    fw_build    INTEGER,
    avg_ua      INTEGER,               -- average current since the tag's boot
    life_days   INTEGER,               -- estimated battery life from that
    fw_at       REAL,                  -- when that report arrived
    poll_s      INTEGER,               -- idle check-in interval the tag acknowledged (SM_OP_SET_POLL)
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS bitmaps (
    key          TEXT PRIMARY KEY,     -- render key (hash of source + options)
    name         TEXT,
    source       TEXT,
    fit          TEXT,
    dither       TEXT,
    angle        INTEGER,
    width        INTEGER NOT NULL,
    height       INTEGER NOT NULL,
    midtone      REAL,
    bw           BLOB,                 -- 5624-byte transport planes
    red          BLOB,
    original_png BLOB NOT NULL,
    device_png   BLOB NOT NULL,
    created_at   REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS bitmaps_created ON bitmaps(created_at DESC);

CREATE TABLE IF NOT EXISTS events (
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at     REAL NOT NULL,
    hex_id TEXT,
    event  TEXT NOT NULL,              -- sync|push|ok|fail|error|boot|bootloader
    detail TEXT
);
CREATE INDEX IF NOT EXISTS events_at ON events(at DESC);
""" + """
CREATE TABLE IF NOT EXISTS voltage (    -- every supply-voltage reading a tag has reported
    id     INTEGER PRIMARY KEY AUTOINCREMENT,
    hex_id TEXT NOT NULL,
    at     REAL NOT NULL,
    raw    INTEGER NOT NULL            -- volts * 256, as the tag sends it
);
CREATE INDEX IF NOT EXISTS voltage_tag_at ON voltage(hex_id, at);

CREATE TABLE IF NOT EXISTS power_runs ( -- an archived power measurement: one battery / firmware
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hex_id     TEXT NOT NULL,
    started_at REAL NOT NULL,          -- the previous archive (or 0: from the first reading)
    ended_at   REAL NOT NULL,          -- when it was archived; the next measurement starts here
    reason     TEXT NOT NULL,          -- battery | firmware | other
    note       TEXT,
    fw         TEXT,                   -- the firmware the tag last reported, e.g. 1.1.0-34
    stats      TEXT,                   -- JSON: App.voltage_history()'s stats at archive time
    points     TEXT                    -- JSON [[t, volts], ...], its own copy of the readings
);
CREATE INDEX IF NOT EXISTS power_runs_tag ON power_runs(hex_id, ended_at);

CREATE TABLE IF NOT EXISTS app_bindings ( -- InkServices: the app that owns a tag's screen.
    hex_id       TEXT PRIMARY KEY,     -- one app per tag. The app's own config and data
    app_id       TEXT NOT NULL,        -- live in its own database (inkservices/appstore.py)
    last_hash    TEXT,                 -- sha1 of the last queued planes: skip identical pushes
    last_push_at REAL
);
"""


class Store:
    """The server's memory across restarts."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._migrate()
        self._trim_events()

    # ── schema ─────────────────────────────────────────────────────────────
    def _migrate(self) -> None:
        version = self._db.execute("PRAGMA user_version").fetchone()[0]
        if version >= SCHEMA_VERSION:
            return
        if version == 0:
            self._db.executescript(_SCHEMA)
        else:
            if version == 1:
                for column in ("fw_version TEXT", "fw_build INTEGER", "avg_ua INTEGER",
                               "life_days INTEGER", "fw_at REAL"):
                    self._db.execute(f"ALTER TABLE tags ADD COLUMN {column}")
            if version <= 5:
                self._db.execute("ALTER TABLE tags ADD COLUMN poll_s INTEGER")
            self._db.executescript(_SCHEMA)     # IF NOT EXISTS: adds voltage, power_runs
        self._db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # ── settings ───────────────────────────────────────────────────────────
    def setting(self, key: str, default=None):
        with self._lock:
            row = self._db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        if row is None:
            return default
        try:
            return json.loads(row["value"])
        except ValueError:
            return default

    def set_setting(self, key: str, value) -> None:
        with self._lock:
            self._db.execute(
                "INSERT INTO settings(key, value, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                (key, json.dumps(value), time.time()),
            )
            self._db.commit()

    def settings(self) -> dict:
        with self._lock:
            rows = self._db.execute("SELECT key, value FROM settings").fetchall()
        out = {}
        for row in rows:
            try:
                out[row["key"]] = json.loads(row["value"])
            except ValueError:
                continue
        return out

    def forget_setting(self, key: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM settings WHERE key=?", (key,))
            self._db.commit()

    # ── tags ───────────────────────────────────────────────────────────────
    def tags(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM tags ORDER BY hex_id").fetchall()
        return [dict(row) for row in rows]

    def _ensure_tag(self, hex_id: str, at: float) -> None:
        self._db.execute(
            "INSERT INTO tags(hex_id, created_at) VALUES(?,?) ON CONFLICT(hex_id) DO NOTHING",
            (hex_id, at),
        )

    def touch_tag(self, hex_id: str, status: str | None = None, at: float | None = None) -> int:
        """A tag announced itself: bump its counter and remember when. Returns the count."""
        when = time.time() if at is None else at
        with self._lock:
            self._ensure_tag(hex_id, when)
            if status is None:
                self._db.execute(
                    "UPDATE tags SET last_seen=?, seen_count=seen_count+1 WHERE hex_id=?",
                    (when, hex_id),
                )
            else:
                self._db.execute(
                    "UPDATE tags SET last_seen=?, seen_count=seen_count+1, last_status=? WHERE hex_id=?",
                    (when, status, hex_id),
                )
            self._db.commit()
            row = self._db.execute("SELECT seen_count FROM tags WHERE hex_id=?", (hex_id,)).fetchone()
        return int(row["seen_count"]) if row else 0

    def record_fw(self, hex_id: str, version: str, build: int, avg_ua: int,
                  life_days: int, at: float | None = None) -> None:
        """Keep the tag's latest firmware version and power figures (newest report wins)."""
        when = time.time() if at is None else at
        with self._lock:
            self._ensure_tag(hex_id, when)
            self._db.execute(
                "UPDATE tags SET fw_version=?, fw_build=?, avg_ua=?, life_days=?, fw_at=? "
                "WHERE hex_id=?", (version, build, avg_ua, life_days, when, hex_id))
            self._db.commit()

    def update_tag(self, hex_id: str, **fields) -> dict | None:
        """Set editable tag fields: alias, notes, grid_row, grid_col, battery, last_status, poll_s."""
        allowed = {"alias", "notes", "grid_row", "grid_col", "battery", "last_status", "poll_s"}
        sets = {k: v for k, v in fields.items() if k in allowed}
        with self._lock:
            self._ensure_tag(hex_id, time.time())
            if sets:
                assignments = ", ".join(f"{k}=?" for k in sets)
                self._db.execute(
                    f"UPDATE tags SET {assignments} WHERE hex_id=?", (*sets.values(), hex_id)
                )
                self._db.commit()
            row = self._db.execute("SELECT * FROM tags WHERE hex_id=?", (hex_id,)).fetchone()
        return dict(row) if row else None

    def rename_tag(self, old_hex: str, new_hex: str) -> bool:
        """Move a tag's row to another id (identity assignment).

        The tag keeps working through the change, but it polls with the new id
        afterwards, so everything the server knew about it - alias, notes, map
        position, counters, last pushed frame - has to move with it.
        """
        with self._lock:
            taken = self._db.execute(
                "SELECT 1 FROM tags WHERE hex_id=?", (new_hex,)
            ).fetchone()
            if taken:
                # the id already belongs to a tag: keep that row, drop the stale one
                self._db.execute("DELETE FROM tags WHERE hex_id=?", (old_hex,))
            else:
                self._db.execute(
                    "UPDATE tags SET hex_id=? WHERE hex_id=?", (new_hex, old_hex)
                )
            self._db.execute(
                "UPDATE voltage SET hex_id=? WHERE hex_id=?", (new_hex, old_hex)
            )
            self._db.execute(
                "UPDATE power_runs SET hex_id=? WHERE hex_id=?", (new_hex, old_hex)
            )
            # the tag's app moves with it; where the new id already has one, that one
            # stays (as with the tag row above). The app's own data is moved by the
            # AppHost, in the app's database.
            self._db.execute(
                "UPDATE OR IGNORE app_bindings SET hex_id=? WHERE hex_id=?", (new_hex, old_hex)
            )
            self._db.execute("DELETE FROM app_bindings WHERE hex_id=?", (old_hex,))
            self._db.commit()
            return not taken

    def forget_tags(self, hex_ids: list[str]) -> int:
        """Delete tag rows, and the events that only exist because of them.

        Removing a tag is a cleanup of the *server's* bookkeeping: nothing is sent
        to the tag, and a tag that keeps polling simply reappears as a new row.
        """
        removed = 0
        with self._lock:
            for hex_id in hex_ids:
                cursor = self._db.execute("DELETE FROM tags WHERE hex_id=?", (hex_id,))
                removed += cursor.rowcount or 0
                self._db.execute("DELETE FROM events WHERE hex_id=?", (hex_id,))
                self._db.execute("DELETE FROM voltage WHERE hex_id=?", (hex_id,))
                self._db.execute("DELETE FROM power_runs WHERE hex_id=?", (hex_id,))
                self._db.execute("DELETE FROM app_bindings WHERE hex_id=?", (hex_id,))
            self._db.commit()
        return removed

    # ── InkServices: which app owns which tag's screen ────────────────────
    @staticmethod
    def _binding_row(row) -> dict:
        return {"hex_id": row["hex_id"], "app_id": row["app_id"],
                "last_hash": row["last_hash"], "last_push_at": row["last_push_at"]}

    def bind_app(self, hex_id: str, app_id: str) -> None:
        """Give a tag's screen to an app (replacing any app it had).

        last_hash is cleared: the new app's first screen must be pushed even if it
        happens to look like the old one's last.
        """
        with self._lock:
            self._db.execute(
                "INSERT INTO app_bindings(hex_id, app_id, last_hash, last_push_at) "
                "VALUES(?,?,NULL,NULL) ON CONFLICT(hex_id) DO UPDATE SET "
                "app_id=excluded.app_id, last_hash=NULL, last_push_at=NULL",
                (hex_id, app_id),
            )
            self._db.commit()

    def unbind_app(self, hex_id: str) -> None:
        with self._lock:
            self._db.execute("DELETE FROM app_bindings WHERE hex_id=?", (hex_id,))
            self._db.commit()

    def app_binding(self, hex_id: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM app_bindings WHERE hex_id=?", (hex_id,)
            ).fetchone()
        return self._binding_row(row) if row else None

    def app_bindings(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM app_bindings ORDER BY hex_id").fetchall()
        return [self._binding_row(row) for row in rows]

    def set_app_pushed(self, hex_id: str, image_hash: str, at: float) -> None:
        """Remember what was last queued for the tag, so an identical screen is skipped."""
        with self._lock:
            self._db.execute(
                "UPDATE app_bindings SET last_hash=?, last_push_at=? WHERE hex_id=?",
                (image_hash, at, hex_id),
            )
            self._db.commit()

    # ── voltage history ────────────────────────────────────────────────────
    def add_voltage(self, hex_id: str, raw: int, at: float | None = None) -> None:
        """Keep one supply-voltage reading (raw = volts * 256) of a tag."""
        when = time.time() if at is None else at
        with self._lock:
            self._db.execute(
                "INSERT INTO voltage(hex_id, at, raw) VALUES(?,?,?)", (hex_id, when, int(raw))
            )
            self._db.commit()

    def voltage_between(self, hex_id: str, since: float, until: float) -> list[tuple[float, float]]:
        """(time, volts) of every reading in [since, until], oldest first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT at, raw FROM voltage WHERE hex_id=? AND at>=? AND at<=? ORDER BY at",
                (hex_id, since, until),
            ).fetchall()
        return [(row["at"], row["raw"] / 256.0) for row in rows]

    # ── archived power measurements ────────────────────────────────────────
    def add_power_run(self, hex_id: str, started_at: float, ended_at: float, reason: str,
                      note: str | None, fw: str | None, stats: dict | None,
                      points: list) -> int:
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO power_runs(hex_id, started_at, ended_at, reason, note, fw, stats, "
                "points) VALUES(?,?,?,?,?,?,?,?)",
                (hex_id, started_at, ended_at, reason, note, fw,
                 json.dumps(stats), json.dumps(points)))
            self._db.commit()
            return int(cursor.lastrowid)

    def last_power_run_end(self, hex_id: str) -> float:
        """Where the current measurement starts: the newest archive, else 0."""
        with self._lock:
            row = self._db.execute(
                "SELECT MAX(ended_at) AS t FROM power_runs WHERE hex_id=?", (hex_id,)).fetchone()
        return float(row["t"]) if row and row["t"] is not None else 0.0

    @staticmethod
    def _run_row(row, with_points: bool) -> dict:
        out = {key: row[key] for key in ("id", "hex_id", "started_at", "ended_at",
                                         "reason", "note", "fw")}
        try:
            out["stats"] = json.loads(row["stats"]) if row["stats"] else None
        except ValueError:
            out["stats"] = None
        if with_points:
            try:
                out["points"] = json.loads(row["points"]) if row["points"] else []
            except ValueError:
                out["points"] = []
        return out

    def power_runs(self, hex_id: str) -> list[dict]:
        """A tag's archived measurements, newest first, without their readings."""
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM power_runs WHERE hex_id=? ORDER BY ended_at DESC",
                (hex_id,)).fetchall()
        return [self._run_row(row, False) for row in rows]

    def power_run(self, run_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM power_runs WHERE id=?", (run_id,)).fetchone()
        return self._run_row(row, True) if row else None

    def delete_power_run(self, run_id: int) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM power_runs WHERE id=?", (run_id,))
            self._db.commit()
        return bool(cursor.rowcount)

    def record_push(self, hex_id: str, name: str, bitmap_key: str | None,
                    at: float | None = None) -> None:
        when = time.time() if at is None else at
        with self._lock:
            self._ensure_tag(hex_id, when)
            self._db.execute(
                "UPDATE tags SET push_name=?, push_key=?, push_at=? WHERE hex_id=?",
                (name, bitmap_key, when, hex_id),
            )
            self._db.commit()

    # ── bitmaps ────────────────────────────────────────────────────────────
    def put_bitmap(self, render, name: str | None = None) -> None:
        """Store a preview.Render so its PNGs outlive the process."""
        with self._lock:
            self._db.execute(
                "INSERT INTO bitmaps(key, name, source, fit, dither, angle, width, height, midtone,"
                " bw, red, original_png, device_png, created_at)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
                " ON CONFLICT(key) DO NOTHING",
                (
                    render.key, name, str(render.source), getattr(render, "fit", None),
                    getattr(render, "dither", None), render.angle,
                    render.size[0], render.size[1], render.midtone,
                    render.bw, render.red, render.original_png, render.device_png, time.time(),
                ),
            )
            self._db.execute(
                "DELETE FROM bitmaps WHERE key NOT IN "
                "(SELECT key FROM bitmaps ORDER BY created_at DESC LIMIT ?)",
                (MAX_BITMAPS,),
            )
            self._db.commit()

    def bitmap(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM bitmaps WHERE key=?", (key,)).fetchone()
        return dict(row) if row else None

    def bitmap_png(self, key: str, kind: str = "device") -> bytes | None:
        column = "original_png" if kind == "original" else "device_png"
        with self._lock:
            row = self._db.execute(
                f"SELECT {column} AS png FROM bitmaps WHERE key=?", (key,)
            ).fetchone()
        return bytes(row["png"]) if row and row["png"] is not None else None

    def recent_bitmaps(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT key, name, source, fit, dither, width, height, created_at"
                " FROM bitmaps ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── events ─────────────────────────────────────────────────────────────
    def add_event(self, event: str, hex_id: str | None = None, detail: str | None = None,
                  at: float | None = None) -> int:
        when = time.time() if at is None else at
        with self._lock:
            cursor = self._db.execute(
                "INSERT INTO events(at, hex_id, event, detail) VALUES(?,?,?,?)",
                (when, hex_id, event, detail),
            )
            self._db.commit()
            return int(cursor.lastrowid)

    def events_since(self, since: int = 0, limit: int = 500) -> list[list]:
        """Newest-first window of events with id > since, returned oldest-first."""
        with self._lock:
            rows = self._db.execute(
                "SELECT id, at, hex_id, event, detail FROM events WHERE id > ?"
                " ORDER BY id DESC LIMIT ?",
                (int(since), limit),
            ).fetchall()
        return [
            [row["id"], row["at"], row["hex_id"], row["event"], row["detail"]]
            for row in reversed(rows)
        ]

    def latest_event_id(self) -> int:
        with self._lock:
            row = self._db.execute("SELECT MAX(id) AS id FROM events").fetchone()
        return int(row["id"] or 0)

    def _trim_events(self) -> None:
        with self._lock:
            self._db.execute(
                "DELETE FROM events WHERE id <= (SELECT MAX(id) - ? FROM events)", (MAX_EVENTS,)
            )
            self._db.commit()
