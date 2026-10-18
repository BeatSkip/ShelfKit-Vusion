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

SCHEMA_VERSION = 1
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
        # future versions: elif version == 1: ALTER TABLE ...
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

    def update_tag(self, hex_id: str, **fields) -> dict | None:
        """Set editable tag fields: alias, notes, grid_row, grid_col, battery, last_status."""
        allowed = {"alias", "notes", "grid_row", "grid_col", "battery", "last_status"}
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
