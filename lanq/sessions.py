import json
import sqlite3

from pydantic import BaseModel

from lanq.clock import utcnow

SESSION_ALREADY_ACTIVE = "A session is already active"
NO_ACTIVE_SESSION = "No session is active"
QUIZ_LOCKED = "Quiz is locked while a session is running"
SESSION_NOT_FOUND = "Session not found"


class StartSessionIn(BaseModel):
    quiz_id: int


def active_session(conn: sqlite3.Connection) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE status = 'active' ORDER BY id DESC LIMIT 1"
    ).fetchone()


def fetch_session(conn: sqlite3.Connection, session_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM sessions WHERE id = ?", (session_id,)
    ).fetchone()


def build_snapshot(conn: sqlite3.Connection, quiz_id: int) -> dict | None:
    quiz = conn.execute(
        "SELECT title, time_limit_seconds FROM quizzes WHERE id = ?", (quiz_id,)
    ).fetchone()
    if quiz is None:
        return None
    rows = conn.execute(
        "SELECT id, text, options_json, correct_index FROM questions"
        " WHERE quiz_id = ? ORDER BY position",
        (quiz_id,),
    ).fetchall()
    return {
        "title": str(quiz["title"]),
        "time_limit_seconds": quiz["time_limit_seconds"],
        "questions": [
            {
                "id": int(row["id"]),
                "text": str(row["text"]),
                "options": json.loads(str(row["options_json"])),
                "correct_index": int(row["correct_index"]),
            }
            for row in rows
        ],
    }


def snapshot_of(row: sqlite3.Row) -> dict:
    return json.loads(str(row["snapshot_json"]))


def session_payload(row: sqlite3.Row) -> dict:
    snapshot = snapshot_of(row)
    return {
        "id": int(row["id"]),
        "quiz_id": int(row["quiz_id"]),
        "status": str(row["status"]),
        "title": str(snapshot["title"]),
        "time_limit_seconds": snapshot["time_limit_seconds"],
        "question_count": len(snapshot["questions"]),
        "started_at": str(row["started_at"]),
        "ended_at": row["ended_at"],
    }


def create_session(conn: sqlite3.Connection, quiz_id: int) -> int | None:
    snapshot = build_snapshot(conn, quiz_id)
    if snapshot is None:
        return None
    cursor = conn.execute(
        "INSERT INTO sessions (quiz_id, snapshot_json, status, started_at)"
        " VALUES (?, ?, 'active', ?)",
        (quiz_id, json.dumps(snapshot), utcnow()),
    )
    session_id = cursor.lastrowid
    assert session_id is not None
    return int(session_id)


def stop_active_session(conn: sqlite3.Connection) -> sqlite3.Row | None:
    row = active_session(conn)
    if row is None:
        return None
    conn.execute(
        "UPDATE sessions SET status = 'ended', ended_at = ? WHERE id = ?",
        (utcnow(), int(row["id"])),
    )
    stopped = fetch_session(conn, int(row["id"]))
    assert stopped is not None
    return stopped


def quiz_is_locked(conn: sqlite3.Connection, quiz_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sessions WHERE quiz_id = ? AND status = 'active'"
        " LIMIT 1",
        (quiz_id,),
    ).fetchone()
    return row is not None


def history_entries(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, COUNT(p.id) AS participant_count"
        " FROM sessions s"
        " LEFT JOIN participants p ON p.session_id = s.id"
        " GROUP BY s.id"
        " ORDER BY s.id DESC"
    ).fetchall()
    entries: list[dict] = []
    for row in rows:
        entry = session_payload(row)
        entry["participant_count"] = int(row["participant_count"])
        entries.append(entry)
    return entries


def delete_session(conn: sqlite3.Connection, session_id: int) -> bool:
    cursor = conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
    return cursor.rowcount == 1
