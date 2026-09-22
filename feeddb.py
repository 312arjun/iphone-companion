"""
feeddb.py - SQLite persistence for the notification feed.

Kept separate from store.py, which is about live state. This is the only
module that knows SQL exists; _Feed talks to it through add/load/prune and
nothing else in the app touches the database.

Threading: the BLE thread writes and the Qt thread reads, so the connection
is opened with check_same_thread=False. That is safe *because* every call
goes through _Feed's existing lock - this module does no locking of its own
and must not be called directly from two threads.

Failure policy: notifications are not worth crashing over. Every operation
swallows sqlite3.Error and degrades to in-memory-only behaviour, because a
locked or corrupt database should cost history, not the running app.
"""

from __future__ import annotations

import json
import sqlite3
import time

import applog
import paths

SCHEMA_VERSION = 2

# Retention: a flat row cap, pruned on startup. Deliberately not also
# age-based - two limits make "why did that vanish?" ambiguous, and a row
# cap is the one a user can reason about.
KEEP_ROWS = 10_000

_conn: sqlite3.Connection | None = None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS notifications (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    at        REAL    NOT NULL,
    app       TEXT    NOT NULL DEFAULT '',
    bundle_id TEXT    NOT NULL DEFAULT '',
    title     TEXT    NOT NULL DEFAULT '',
    body      TEXT    NOT NULL DEFAULT '',
    category  TEXT    NOT NULL DEFAULT '',
    uid       INTEGER,
    actions   TEXT    NOT NULL DEFAULT '[]',
    style     TEXT,
    -- what rules.py decided: 'show' or 'silent'. Dropped notifications are
    -- never stored, so 'drop' never appears here. Added in schema 2; rows
    -- written before that migrate to 'show', which is what they were.
    verdict   TEXT    NOT NULL DEFAULT 'show'
);
-- newest-first paging, which is every read the UI does
CREATE INDEX IF NOT EXISTS idx_notif_at ON notifications(at DESC);
-- per-app filtering (scope item 2) and grouping (item 6)
CREATE INDEX IF NOT EXISTS idx_notif_bundle ON notifications(bundle_id, at DESC);
"""


def connect() -> sqlite3.Connection | None:
    """Open and migrate the database. Returns None if it cannot be used."""
    global _conn
    if _conn is not None:
        return _conn
    try:
        conn = sqlite3.connect(paths.FEED_DB, check_same_thread=False)
        # WAL lets the Qt thread read while the BLE thread writes without
        # either blocking the other.
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.executescript(_SCHEMA)
        _migrate(conn)
        conn.commit()
        _conn = conn
        applog.log("feed database ready at %s" % paths.FEED_DB, "store")
        return _conn
    except sqlite3.Error as exc:
        applog.log("feed database unavailable (%s) - history will not "
                   "persist this session" % exc, "store")
        return None


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Bring an existing database up to SCHEMA_VERSION.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already
    exists, so a new column has to be added explicitly. The columns are
    read back rather than trusting user_version, because a database created
    fresh by _SCHEMA already has `verdict` while still reporting version 0 -
    checking the version alone would try to add a column that is there.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version >= SCHEMA_VERSION:
        return
    have = {row[1] for row in conn.execute("PRAGMA table_info(notifications)")}
    if "verdict" not in have:
        conn.execute("ALTER TABLE notifications ADD COLUMN verdict TEXT "
                     "NOT NULL DEFAULT 'show'")
        applog.log("feed database migrated to schema %d (added verdict)"
                   % SCHEMA_VERSION, "store")
    conn.execute("PRAGMA user_version=%d" % SCHEMA_VERSION)


# Rows are exchanged as plain dicts, never as store.Item - feeddb must not
# import store, because store imports feeddb.
_COLUMNS = ("at", "app", "bundle_id", "title", "body", "category", "uid",
            "actions", "style", "verdict")


def _row_to_dict(row) -> dict:
    data = dict(zip(_COLUMNS, row))
    try:
        data["actions"] = json.loads(data["actions"] or "[]")
    except (ValueError, TypeError):
        data["actions"] = []
    return data


def add(item: dict) -> None:
    """Persist one notification. Silent on failure by design."""
    conn = connect()
    if conn is None:
        return
    try:
        conn.execute(
            "INSERT INTO notifications (at, app, bundle_id, title, body,"
            " category, uid, actions, style, verdict)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            (item.get("at") or time.time(),
             item.get("app") or "",
             item.get("bundle_id") or "",
             item.get("title") or "",
             item.get("body") or "",
             item.get("category") or "",
             item.get("uid"),
             json.dumps(item.get("actions") or []),
             item.get("style"),
             item.get("verdict") or "show"))
        conn.commit()
    except sqlite3.Error as exc:
        applog.log("feed insert failed: %s" % exc, "store")


def load(limit: int) -> list[dict]:
    """The newest `limit` notifications, newest first."""
    conn = connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT at, app, bundle_id, title, body, category, uid, actions,"
            " style, verdict FROM notifications ORDER BY at DESC"
            " LIMIT ?",
            (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        applog.log("feed load failed: %s" % exc, "store")
        return []


def stored_count() -> int:
    """All-time rows retained. Distinct from _Feed.count(), which is
    notifications seen *this session* and drives the Device Info page."""
    conn = connect()
    if conn is None:
        return 0
    try:
        return conn.execute("SELECT COUNT(*) FROM notifications").fetchone()[0]
    except sqlite3.Error:
        return 0


def prune() -> int:
    """Drop history past the row cap. Returns rows removed."""
    conn = connect()
    if conn is None:
        return 0
    removed = 0
    try:
        cur = conn.execute(
            "DELETE FROM notifications WHERE id NOT IN ("
            "  SELECT id FROM notifications ORDER BY at DESC LIMIT ?)",
            (KEEP_ROWS,))
        removed += cur.rowcount or 0
        conn.commit()
        if removed:
            applog.log("pruned %d old notification(s)" % removed, "store")
    except sqlite3.Error as exc:
        applog.log("feed prune failed: %s" % exc, "store")
    return removed


def clear() -> None:
    """Wipe stored history. The in-memory deque is cleared separately."""
    conn = connect()
    if conn is None:
        return
    try:
        conn.execute("DELETE FROM notifications")
        conn.commit()
        applog.log("notification history cleared", "store")
    except sqlite3.Error as exc:
        applog.log("feed clear failed: %s" % exc, "store")


def search(query: str = "", bundle_id: str = "", limit: int = 200,
           since: float | None = None) -> list[dict]:
    """
    Filtered history, newest first.

    LIKE rather than FTS5 on purpose: the table is capped at KEEP_ROWS, and
    a scan over ten thousand short rows is well under a frame at 60fps. FTS
    would mean a second table kept in sync for no gain at this size. Revisit
    only if KEEP_ROWS grows by an order of magnitude.

    `query` matches title or body, case-insensitively. `bundle_id` narrows
    to one app and uses the (bundle_id, at) index.
    """
    conn = connect()
    if conn is None:
        return []
    where, params = [], []
    if query:
        # escape LIKE wildcards so a literal % or _ in a search box does not
        # silently match everything
        safe = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        where.append("(title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\')")
        params += ["%" + safe + "%"] * 2
    if bundle_id:
        where.append("bundle_id = ?")
        params.append(bundle_id)
    if since is not None:
        where.append("at >= ?")
        params.append(since)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    try:
        rows = conn.execute(
            "SELECT at, app, bundle_id, title, body, category, uid, actions,"
            " style, verdict FROM notifications" + clause +
            " ORDER BY at DESC LIMIT ?",
            params + [limit]).fetchall()
        return [_row_to_dict(r) for r in rows]
    except sqlite3.Error as exc:
        applog.log("feed search failed: %s" % exc, "store")
        return []


def apps(limit: int = 60) -> list[dict]:
    """
    Every app seen, with counts and most recent activity.

    Drives both the grouped view (item 6) and the app pickers in Settings,
    so the filter lists offer real bundles rather than asking the user to
    type an identifier they have never seen.
    """
    conn = connect()
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT bundle_id, MAX(app), COUNT(*), MAX(at) FROM notifications"
            " GROUP BY bundle_id ORDER BY MAX(at) DESC LIMIT ?",
            (limit,)).fetchall()
        return [{"bundle_id": r[0], "app": r[1], "count": r[2], "last": r[3]}
                for r in rows]
    except sqlite3.Error as exc:
        applog.log("feed apps query failed: %s" % exc, "store")
        return []
