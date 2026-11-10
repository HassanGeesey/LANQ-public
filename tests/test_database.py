import json
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lanq.main import create_app
from lanq import paths

REQUIRED_TABLES = {
    "quizzes",
    "questions",
    "sessions",
    "participants",
    "answers",
}

LEGACY_SESSIONS_TABLE = """
CREATE TABLE sessions (
    id INTEGER PRIMARY KEY,
    quiz_id INTEGER NOT NULL REFERENCES quizzes(id),
    snapshot_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('active', 'ended')),
    started_at TEXT NOT NULL,
    ended_at TEXT
);
"""

LEGACY_SNAPSHOT = {
    "title": "Legacy quiz",
    "time_limit_seconds": None,
    "questions": [
        {
            "id": 7,
            "text": "Capital of France?",
            "options": ["Paris", "Rome"],
            "correct_index": 0,
        }
    ],
}


def table_names(db_path: Path) -> set[str]:
    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    return {name for (name,) in rows}


def test_schema_exists_after_boot(db_path: Path) -> None:
    create_app(db_path=db_path)
    assert REQUIRED_TABLES <= table_names(db_path)


def test_db_init_is_idempotent(db_path: Path) -> None:
    create_app(db_path=db_path)
    create_app(db_path=db_path)
    assert REQUIRED_TABLES <= table_names(db_path)


def test_frozen_windows_database_uses_programdata(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(paths.sys, "platform", "win32")
    monkeypatch.setattr(paths.sys, "frozen", True, raising=False)
    monkeypatch.setenv("PROGRAMDATA", str(tmp_path))

    assert paths._default_db_path() == tmp_path / "LANQ" / "data" / "lanq.db"


def test_second_boot_serves_requests(db_path: Path) -> None:
    create_app(db_path=db_path)
    with TestClient(create_app(db_path=db_path)) as second:
        assert second.get("/api/student/state").status_code == 200


def test_a_database_from_before_the_session_fk_drop_keeps_working(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_SESSIONS_TABLE)
        conn.execute(
            "INSERT INTO sessions (quiz_id, snapshot_json, status, started_at)"
            " VALUES (?, ?, 'active', ?)",
            (999, json.dumps(LEGACY_SNAPSHOT), "2026-01-01T00:00:00+00:00"),
        )
        conn.commit()

    app = create_app(db_path=db_path)
    with TestClient(app) as client:
        browser = TestClient(app)
        joined = browser.post(
            "/api/student/join",
            json={"student_id": "s-001", "name": "Ada"},
        )
        assert joined.status_code == 201, joined.text
        quiz = browser.get("/api/student/quiz")
        assert quiz.status_code == 200, quiz.text
        assert quiz.json()["title"] == "Legacy quiz"

        setup = client.post(
            "/api/admin/setup",
            json={"username": "ms.Rivera", "password": "correct horse"},
        )
        assert setup.status_code == 201
        login = client.post(
            "/api/admin/login",
            json={"username": "ms.Rivera", "password": "correct horse"},
        )
        assert login.status_code == 200
        assert client.post("/api/admin/sessions/stop").status_code == 200

        created = client.post(
            "/api/admin/quizzes",
            json={
                "title": "Fresh quiz",
                "questions": [
                    {
                        "text": "Q1",
                        "options": [
                            {"text": "a", "correct": True},
                            {"text": "b", "correct": False},
                        ],
                    }
                ],
            },
        )
        assert created.status_code == 201
        started = client.post(
            "/api/admin/sessions", json={"quiz_id": created.json()["id"]}
        )
        assert started.status_code == 201
        assert client.post("/api/admin/sessions/stop").status_code == 200

        deleted = client.delete(f"/api/admin/quizzes/{created.json()['id']}")
        assert deleted.status_code == 200, deleted.text
