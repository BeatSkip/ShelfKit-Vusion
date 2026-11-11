"""One SQLite database per app: everything the app keeps, and nothing of anyone else's.

The file lives inside the app's own folder, `inkapps/<id>/data/app.db`, so the folder
*is* the app: copy it to another server and the code, its per-tag settings and its
data all come along. `data/` is git-ignored, so pulling a new version of the app or
committing it in the Dev tab never touches what it has stored.

What the server keeps here for the app (tables prefixed `ink_`, so they cannot clash
with the app's own):

* `ink_config` - per tag, the settings the user gave the app for that tag (JSON),
* `ink_state`  - per tag, the app's working data (JSON). hex_id '' is the app-wide
  document shared by all its tags,
* `ink_meta`   - which app the file belongs to and its layout version.

The app may create its own tables through `AppStore.sql` (a plain sqlite3
connection) for anything that does not fit a JSON document: logs, history,
usage figures.

Which tag runs which app is *not* here: that is the server's decision and lives in
the main store (`app_bindings`), so two apps can never both claim a tag.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

LAYOUT_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ink_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ink_config (
    hex_id     TEXT PRIMARY KEY,
    data       TEXT NOT NULL,          -- JSON
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS ink_state (
    hex_id     TEXT PRIMARY KEY,       -- '' = shared by every tag running the app
    data       TEXT NOT NULL,          -- JSON
    updated_at REAL NOT NULL
);
"""


def app_db_path(app_dir: Path) -> Path:
    return Path(app_dir) / "data" / "app.db"


class AppStoreError(Exception):
    """The database belongs to another app, or cannot be opened."""


class AppStore:
    """An app's private database. One instance per app, shared by its tags."""

    def __init__(self, path: str | Path, app_id: str) -> None:
        self.path = Path(path)
        self.app_id = app_id
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(str(self.path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        with self._lock:
            self._db.execute("PRAGMA journal_mode=WAL")
            self._db.execute("PRAGMA synchronous=NORMAL")
            self._db.executescript(_SCHEMA)
            owner = self._meta("app_id")
            if owner is None:
                self._set_meta("app_id", app_id)
                self._set_meta("layout", str(LAYOUT_VERSION))
            elif owner != app_id:
                self._db.close()
                raise AppStoreError(f"{self.path} belongs to app {owner!r}, not {app_id!r}")
            self._db.commit()

    # ── housekeeping ───────────────────────────────────────────────────────
    def _meta(self, key: str) -> str | None:
        row = self._db.execute("SELECT value FROM ink_meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def _set_meta(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT INTO ink_meta(key, value) VALUES(?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value)
        )

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @property
    def sql(self) -> sqlite3.Connection:
        """The raw connection, for the app's own tables. The app commits its own writes."""
        return self._db

    # ── JSON documents ─────────────────────────────────────────────────────
    def _get(self, table: str, hex_id: str) -> dict:
        with self._lock:
            row = self._db.execute(
                f"SELECT data FROM {table} WHERE hex_id=?", (hex_id,)
            ).fetchone()
        if row is None:
            return {}
        try:
            data = json.loads(row["data"])
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def _put(self, table: str, hex_id: str, data: dict) -> None:
        with self._lock:
            self._db.execute(
                f"INSERT INTO {table}(hex_id, data, updated_at) VALUES(?,?,?) "
                "ON CONFLICT(hex_id) DO UPDATE SET data=excluded.data, "
                "updated_at=excluded.updated_at",
                (hex_id, json.dumps(data), time.time()),
            )
            self._db.commit()

    def config(self, hex_id: str) -> dict:
        """The user's settings for this app on this tag. {} when none."""
        return self._get("ink_config", hex_id)

    def set_config(self, hex_id: str, data: dict) -> None:
        self._put("ink_config", hex_id, data)

    def state(self, hex_id: str) -> dict:
        """The app's data for one tag, or its shared data with hex_id ''. {} when none."""
        return self._get("ink_state", hex_id)

    def set_state(self, hex_id: str, data: dict) -> None:
        self._put("ink_state", hex_id, data)

    def tags(self) -> list[str]:
        """Every tag this app holds settings or data for (not the shared '' row)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT hex_id FROM ink_config UNION SELECT hex_id FROM ink_state "
                "ORDER BY 1"
            ).fetchall()
        return [row[0] for row in rows if row[0]]

    def dump(self) -> dict:
        """Everything the server keeps for the app, for the Apps tab's data viewer:
        {"config": {hex: {...}}, "state": {hex: {...}}, "updated": {hex: t},
         "tables": [{"name", "rows"}]} - the app's own tables are counted, not read."""
        out = {"config": {}, "state": {}, "updated": {}, "tables": []}
        with self._lock:
            for table, key in (("ink_config", "config"), ("ink_state", "state")):
                for row in self._db.execute(f"SELECT hex_id, data, updated_at FROM {table}"):
                    try:
                        data = json.loads(row["data"])
                    except ValueError:
                        data = {}
                    out[key][row["hex_id"]] = data if isinstance(data, dict) else {}
                    out["updated"][row["hex_id"]] = max(out["updated"].get(row["hex_id"], 0),
                                                        row["updated_at"])
            names = [r[0] for r in self._db.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'ink\\_%' ESCAPE '\\' AND name NOT LIKE 'sqlite\\_%' ESCAPE '\\' "
                "ORDER BY name")]
            for name in names:
                quoted = '"' + name.replace('"', '""') + '"'
                rows = self._db.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0]
                out["tables"].append({"name": name, "rows": rows})
        return out

    # ── a tag changing id or being forgotten ──────────────────────────────
    def rename_tag(self, old_hex: str, new_hex: str) -> None:
        """Follow a tag to its new id. Where the new id already has data, that stays."""
        if not old_hex or not new_hex:
            return
        with self._lock:
            for table in ("ink_config", "ink_state"):
                self._db.execute(
                    f"UPDATE OR IGNORE {table} SET hex_id=? WHERE hex_id=?", (new_hex, old_hex)
                )
                self._db.execute(f"DELETE FROM {table} WHERE hex_id=?", (old_hex,))
            self._db.commit()

    def forget_tag(self, hex_id: str) -> None:
        """Drop one tag's settings and data. The shared '' document is never touched."""
        if not hex_id:
            return
        with self._lock:
            for table in ("ink_config", "ink_state"):
                self._db.execute(f"DELETE FROM {table} WHERE hex_id=?", (hex_id,))
            self._db.commit()
