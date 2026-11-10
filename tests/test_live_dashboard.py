import sqlite3
from collections.abc import Callable
from pathlib import Path

from fastapi.testclient import TestClient

from tests.helpers import (
    answer,
    answer_every,
    correct_position,
    correct_texts,
    joined_student,
    live,
    submit,
)


def set_submitted_at(db_path: Path, student_id: str, submitted_at: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE participants SET submitted_at = ? WHERE student_id = ?",
            (submitted_at, student_id),
        )
        conn.commit()


def test_live_dashboard_requires_authentication(client: TestClient) -> None:
    assert live(client).status_code == 401


def test_live_dashboard_without_an_active_session_is_empty(
    admin_client: TestClient,
) -> None:
    response = live(admin_client)

    assert response.status_code == 200
    data = response.json()
    assert data["session"] is None
    assert data["roster"] == []
    assert data["leaderboard"] == []


def test_live_dashboard_on_an_active_session_with_no_participants_is_empty(
    admin_client: TestClient, running_session: dict
) -> None:
    response = live(admin_client)

    assert response.status_code == 200
    data = response.json()
    assert data["session"]["id"] == running_session["id"]
    assert data["roster"] == []
    assert data["leaderboard"] == []


def test_roster_reports_all_three_participant_statuses(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    joined_student(student, student_id="s-joined", name="Joined Only")

    working = joined_student(student, student_id="s-working", name="Working")
    texts = correct_texts(capitals_quiz)
    first = working.get("/api/student/quiz").json()["questions"][0]
    assert answer(
        working, first["id"], correct_position(first, texts)
    ).status_code == 200

    done = joined_student(student, student_id="s-done", name="Done")
    answer_every(done, lambda q: correct_position(q, texts))
    assert submit(done).status_code == 200

    data = live(admin_client).json()

    assert [entry["student_id"] for entry in data["roster"]] == [
        "s-joined",
        "s-working",
        "s-done",
    ]
    roster = {entry["student_id"]: entry for entry in data["roster"]}
    assert roster["s-joined"]["status"] == "joined"
    assert roster["s-joined"]["score"] is None
    assert roster["s-working"]["status"] == "in_progress"
    assert roster["s-done"]["status"] == "submitted"
    assert roster["s-done"]["score"] == 5
    for entry in data["roster"]:
        assert entry["name"]
        assert entry["joined_at"]


def test_in_progress_roster_entry_shows_the_current_score(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student, student_id="s-partial", name="Partial")
    texts = correct_texts(capitals_quiz)
    payload = client.get("/api/student/quiz").json()
    for question in payload["questions"][:2]:
        assert answer(
            client, question["id"], correct_position(question, texts)
        ).status_code == 200

    data = live(admin_client).json()

    assert len(data["roster"]) == 1
    entry = data["roster"][0]
    assert entry["status"] == "in_progress"
    assert entry["score"] == 2


def test_leaderboard_ranks_by_score_then_submission_time(
    admin_client: TestClient,
    db_path: Path,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)

    early = joined_student(student, student_id="s-early", name="Early")
    answer_every(early, lambda q: correct_position(q, texts))
    assert submit(early).status_code == 200

    late = joined_student(student, student_id="s-late", name="Late")
    answer_every(late, lambda q: correct_position(q, texts))
    assert submit(late).status_code == 200

    low = joined_student(student, student_id="s-low", name="Low")
    answer_every(
        low,
        lambda q: next(
            index
            for index, option in enumerate(q["options"])
            if option != texts[q["text"]]
        ),
    )
    assert submit(low).status_code == 200

    joined_student(student, student_id="s-working", name="Working")

    set_submitted_at(db_path, "s-early", "2026-01-01T10:00:05+00:00")
    set_submitted_at(db_path, "s-late", "2026-01-01T10:00:01+00:00")
    set_submitted_at(db_path, "s-low", "2026-01-01T09:00:00+00:00")

    data = live(admin_client).json()

    board = data["leaderboard"]
    assert [row["student_id"] for row in board] == ["s-late", "s-early", "s-low"]
    assert [row["rank"] for row in board] == [1, 2, 3]
    assert [row["score"] for row in board] == [5, 5, 0]
    for row in board:
        assert row["name"]
        assert row["submitted_at"]
    assert "s-working" not in {row["student_id"] for row in board}


def test_admin_page_renders_roster_and_leaderboard_views(
    client: TestClient,
) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    for element_id in (
        "dashboard-tab",
        "live-results",
        "outcomes-chart",
        "roster-empty",
        "roster-table",
        "leaderboard-empty",
        "leaderboard-table",
    ):
        assert f'id="{element_id}"' in response.text, element_id
    dashboard = response.text.split('<section id="dashboard-tab"', 1)[1].split(
        '<section id="library-tab"', 1
    )[0]
    live_session = response.text.split('<section id="session-tab"', 1)[1].split(
        '<section id="history-tab"', 1
    )[0]
    assert 'id="live-results"' in dashboard
    assert 'id="live-results"' not in live_session
