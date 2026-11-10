import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS admin_tokens (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quizzes (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    time_limit_seconds INTEGER,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    id INTEGER PRIMARY KEY,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_index INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    quiz_id INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    started_at TEXT NOT NULL,
    ended_at TEXT
);

CREATE TABLE IF NOT EXISTS participants (
    id INTEGER PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    student_id TEXT NOT NULL,
    name TEXT NOT NULL,
    joined_at TEXT NOT NULL,
    submitted_at TEXT,
    shuffle_seed TEXT NOT NULL,
    question_order_json TEXT NOT NULL,
    option_orders_json TEXT NOT NULL,
    score INTEGER,
    auth_token TEXT UNIQUE,
    finalized_by TEXT
);

CREATE TABLE IF NOT EXISTS answers (
    participant_id INTEGER NOT NULL REFERENCES participants(id) ON DELETE CASCADE,
    question_id INTEGER NOT NULL,
    chosen_index INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (participant_id, question_id)
);
"""


ONE_ACTIVE_SESSION_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS one_active_session
    ON sessions (status) WHERE status = 'active';
"""

LEGACY_SESSIONS_REBUILD = """
CREATE TABLE sessions_migrated (
    id INTEGER PRIMARY KEY,
    quiz_id INTEGER NOT NULL,
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    started_at TEXT NOT NULL,
    ended_at TEXT
);
INSERT INTO sessions_migrated
    (id, quiz_id, snapshot_json, status, started_at, ended_at)
    SELECT id, quiz_id, snapshot_json, status, started_at, ended_at
    FROM sessions;
DROP TABLE sessions;
ALTER TABLE sessions_migrated RENAME TO sessions;
"""


def drop_sessions_quiz_reference(conn: sqlite3.Connection) -> None:
    foreign_keys = conn.execute("PRAGMA foreign_key_list('sessions')").fetchall()
    if not any(str(row[2]) == "quizzes" for row in foreign_keys):
        return
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.executescript(LEGACY_SESSIONS_REBUILD)
    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON")


def _migrate_participants_add_finalized_by(conn: sqlite3.Connection) -> None:
    columns = conn.execute("PRAGMA table_info('participants')").fetchall()
    if any(str(column[1]) == "finalized_by" for column in columns):
        return
    conn.execute("ALTER TABLE participants ADD COLUMN finalized_by TEXT")


def init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(SCHEMA)
        drop_sessions_quiz_reference(conn)
        _migrate_participants_add_finalized_by(conn)
        conn.executescript(ONE_ACTIVE_SESSION_INDEX)
        conn.commit()


@contextmanager
def connect(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
