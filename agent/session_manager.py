import os
import sqlite3
from datetime import datetime

# In-memory sessions store for live objects (LLM, managers, etc.)
sessions = {}

_db_path = None


def set_db_path(db_path):
    """Configure the SQLite database path and initialize schema."""
    global _db_path
    _db_path = db_path
    # Ensure parent directory exists
    parent_dir = os.path.dirname(_db_path or "")
    if parent_dir and not os.path.exists(parent_dir):
        os.makedirs(parent_dir, exist_ok=True)
    _initialize_db()


def _get_connection():
    if not _db_path:
        raise RuntimeError(
            "Session DB is not configured. Set DB_PATH in app config or call set_db_path()."
        )
    return sqlite3.connect(_db_path)


def _initialize_db():
    if not _db_path:
        return
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sessions (
                id TEXT PRIMARY KEY,
                auto_confirm INTEGER NOT NULL,
                connected_at TEXT NOT NULL,
                last_active_at TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                FOREIGN KEY(session_id) REFERENCES sessions(id) ON DELETE CASCADE
            )
            """
        )
        # Improve write concurrency
        cur.execute("PRAGMA journal_mode=WAL;")
        conn.commit()


def create_session(session_id, auto_confirm):
    """Persist a new session record."""
    now = datetime.now().isoformat()
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT OR REPLACE INTO sessions (id, auto_confirm, connected_at, last_active_at) VALUES (?, ?, ?, ?)",
            (session_id, 1 if auto_confirm else 0, now, now),
        )
        conn.commit()


def delete_session(session_id):
    """Remove a session and its messages."""
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
        cur.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
        conn.commit()


def touch_session(session_id):
    """Update last_active timestamp for a session."""
    now = datetime.now().isoformat()
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (now, session_id))
        conn.commit()


def set_auto_confirm(session_id, enabled):
    """Persist auto_confirm change for a session."""
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sessions SET auto_confirm = ? WHERE id = ?",
            (1 if enabled else 0, session_id),
        )
        conn.commit()


def add_message(session_id, message_type, content, timestamp=None):
    """Persist a message for a session."""
    ts = timestamp or datetime.now().isoformat()
    with _get_connection() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (session_id, type, content, timestamp) VALUES (?, ?, ?, ?)",
            (session_id, message_type, content, ts),
        )
        # Keep session last_active updated
        cur.execute("UPDATE sessions SET last_active_at = ? WHERE id = ?", (ts, session_id))
        conn.commit()


def get_messages(session_id, limit=None, offset=0):
    """Retrieve messages for a session."""
    with _get_connection() as conn:
        cur = conn.cursor()
        sql = (
            "SELECT type, content, timestamp FROM messages WHERE session_id = ? ORDER BY id ASC"
        )
        params = [session_id]
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        cur.execute(sql, tuple(params))
        rows = cur.fetchall()
        return [
            {"type": row[0], "content": row[1], "timestamp": row[2]}
            for row in rows
        ]