"""SQLite database initialization and CRUD operations."""
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from .config import DB_PATH, ensure_directories


def get_connection() -> sqlite3.Connection:
    ensure_directories()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    """Create tables if they don't exist."""
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            audio_path TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS segments (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            speaker TEXT NOT NULL DEFAULT '',
            start_time REAL NOT NULL DEFAULT 0,
            end_time REAL NOT NULL DEFAULT 0,
            original_text TEXT NOT NULL DEFAULT '',
            edited_text TEXT NOT NULL DEFAULT '',
            seg_audio_path TEXT,
            dubbed_audio_path TEXT,
            dub_status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
        );
    """)
    conn.commit()
    conn.close()
    _migrate()


def _migrate():
    """Add columns that may not exist in older DB versions."""
    conn = get_connection()
    try:
        conn.execute("ALTER TABLE segments ADD COLUMN dub_time REAL NOT NULL DEFAULT 0")
    except Exception:
        pass
    conn.commit()
    conn.close()


def create_project(name: str) -> dict:
    conn = get_connection()
    project_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn.execute(
        "INSERT INTO projects (id, name, status, created_at) VALUES (?, ?, 'new', ?)",
        (project_id, name, now),
    )
    conn.commit()
    conn.close()
    return {"id": project_id, "name": name, "audio_path": None, "status": "pending", "created_at": now}


def get_projects() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT id, name, audio_path, status, created_at FROM projects ORDER BY created_at DESC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_project(project_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT id, name, audio_path, status, created_at FROM projects WHERE id = ?",
        (project_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def update_project(project_id: str, **kwargs):
    allowed = {"name", "audio_path", "status"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [project_id]
    conn = get_connection()
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()


def delete_project(project_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM segments WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()
    conn.close()


def create_segment(project_id: str, speaker: str, start_time: float, end_time: float,
                   original_text: str) -> dict:
    conn = get_connection()
    seg_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    conn.execute(
        """INSERT INTO segments (id, project_id, speaker, start_time, end_time,
           original_text, edited_text, dub_status, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
        (seg_id, project_id, speaker, start_time, end_time, original_text, original_text, now),
    )
    conn.commit()
    conn.close()
    return {
        "id": seg_id, "project_id": project_id, "speaker": speaker,
        "start_time": start_time, "end_time": end_time,
        "original_text": original_text, "edited_text": original_text,
        "seg_audio_path": None, "dubbed_audio_path": None, "dub_status": "pending",
    }


def clear_segments(project_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM segments WHERE project_id = ?", (project_id,))
    conn.commit()
    conn.close()


def get_segments(project_id: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        """SELECT id, project_id, speaker, start_time, end_time,
           original_text, edited_text, seg_audio_path, dubbed_audio_path, dub_status, dub_time
           FROM segments WHERE project_id = ? ORDER BY start_time""",
        (project_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_segment(segment_id: str) -> dict | None:
    conn = get_connection()
    row = conn.execute(
        """SELECT id, project_id, speaker, start_time, end_time,
           original_text, edited_text, seg_audio_path, dubbed_audio_path, dub_status, dub_time
           FROM segments WHERE id = ?""",
        (segment_id,),
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_segment(segment_id: str):
    conn = get_connection()
    conn.execute("DELETE FROM segments WHERE id = ?", (segment_id,))
    conn.commit()
    conn.close()


def update_segment(segment_id: str, **kwargs):
    allowed = {"original_text", "edited_text", "seg_audio_path", "dubbed_audio_path",
               "dub_status", "start_time", "end_time", "emotion", "duration", "dub_time"}
    updates = {k: v for k, v in kwargs.items() if k in allowed}
    if not updates:
        return
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    values = list(updates.values()) + [segment_id]
    conn = get_connection()
    conn.execute(f"UPDATE segments SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()
