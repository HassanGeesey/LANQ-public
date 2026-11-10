import sqlite3
from collections.abc import Callable
from datetime import timedelta, datetime
from pathlib import Path

from fastapi.testclient import TestClient

from lanq.clock import utcnow
from tests.helpers import COOKIE, create_quiz, joined_student, quiz_payload, start_session


def timed_session(admin_client: TestClient) -> dict:
    quiz = create_quiz(admin_client, "Timed")
    return start_session(admin_client, quiz["id"])


def correct_texts(quiz: dict) -> dict[str, str]:
    return {
        question["text"]: next(
            option["text"] for option in question["options"] if option["correct"]
        )
        for question in quiz["questions"]
    }


def answer_questions(
    client: TestClient,
    questions: list[dict],
    texts: dict[str, str],
    correct_count: int | None = None,
) -> None:
    for index, question in enumerate(questions):
        if correct_count is None or index < correct_count:
            position = question["options"].index(texts[question["text"]])
        else:
            position = next(
                i
                for i, option in enumerate(question["options"])
                if option != texts[question["text"]]
            )
        assert client.post(
            "/api/student/answer",
            json={"question_id": question["id"], "position": position},
        ).status_code == 200


def backdate_joined_at(db_path: Path, token: str, delta: timedelta) -> None:
    past = datetime.fromisoformat(utcnow()) - delta
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE participants SET joined_at = ? WHERE auth_token = ?",
            (past.isoformat(), token),
        )
        conn.commit()


def participant_row(db_path: Path, token: str) -> sqlite3.Row:
    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT student_id, joined_at, submitted_at, score, finalized_by"
            " FROM participants WHERE auth_token = ?",
            (token,),
        ).fetchone()
    assert row is not None
    return row


def test_quiz_payload_includes_deadline_for_timed_quiz(
    admin_client: TestClient,
    db_path: Path,
    student: Callable[[], TestClient],
) -> None:
    session = timed_session(admin_client)
    assert session["time_limit_seconds"] is not None

    sclient = student()
    sclient.post("/api/student/join", json={"student_id": "s-001", "name": "Ada"})
    token = sclient.cookies.get(COOKIE)
    assert token

    joined = str(participant_row(db_path, token)["joined_at"])

    resp = sclient.get("/api/student/quiz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["deadline"] is not None
    assert "server_time" in data
    joined_dt = datetime.fromisoformat(joined.replace("Z", "+00:00"))
    deadline_dt = datetime.fromisoformat(data["deadline"].replace("Z", "+00:00"))
    expected = joined_dt + timedelta(seconds=session["time_limit_seconds"])
    assert abs((deadline_dt - expected).total_seconds()) < 2


def test_late_joiner_gets_the_full_time_allowance(
    admin_client: TestClient,
    db_path: Path,
    student: Callable[[], TestClient],
) -> None:
    session = timed_session(admin_client)
    limit = session["time_limit_seconds"]
    assert limit is not None
    with sqlite3.connect(db_path) as conn:
        long_ago = datetime.fromisoformat(utcnow()) - timedelta(minutes=30)
        conn.execute(
            "UPDATE sessions SET started_at = ? WHERE id = ?",
            (long_ago.isoformat(), session["id"]),
        )
        conn.commit()

    client = student()
    assert client.post(
        "/api/student/join", json={"student_id": "s-001", "name": "Ada"}
    ).status_code == 201
    token = client.cookies.get(COOKIE)
    assert token

    data = client.get("/api/student/quiz").json()
    joined_dt = datetime.fromisoformat(
        str(participant_row(db_path, token)["joined_at"]).replace("Z", "+00:00")
    )
    deadline_dt = datetime.fromisoformat(data["deadline"].replace("Z", "+00:00"))
    now_dt = datetime.fromisoformat(utcnow())

    assert deadline_dt > now_dt
    assert abs((deadline_dt - (joined_dt + timedelta(seconds=limit))).total_seconds()) < 2


def test_untimed_quiz_has_no_deadline(
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    payload = quiz_payload("Untimed")
    payload["time_limit_seconds"] = None
    resp = admin_client.post("/api/admin/quizzes", json=payload)
    assert resp.status_code == 201
    quiz = resp.json()
    session = start_session(admin_client, quiz["id"])
    assert session["time_limit_seconds"] is None

    sclient = student()
    sclient.post("/api/student/join", json={"student_id": "s-001", "name": "Ada"})
    resp = sclient.get("/api/student/quiz")
    assert resp.status_code == 200
    data = resp.json()
    assert data["time_limit_seconds"] is None
    assert data["deadline"] is None


def test_expiry_grades_saved_answers_and_finalizes(
    admin_client: TestClient,
    db_path: Path,
    student: Callable[[], TestClient],
) -> None:
    quiz = create_quiz(admin_client, "Timed")
    texts = correct_texts(quiz)
    start_session(admin_client, quiz["id"])
    client = joined_student(student, "s-001", "Ada")
    token = client.cookies.get(COOKIE)

    payload = client.get("/api/student/quiz").json()
    answer_questions(client, payload["questions"], texts, correct_count=2)

    backdate_joined_at(db_path, token, timedelta(seconds=600 + 60))

    state = client.get("/api/student/state")

    assert state.status_code == 200
    assert state.json() == {"state": "ended"}
    row = participant_row(db_path, token)
    assert row["score"] == 2
    assert row["finalized_by"] == "expiry"
    assert row["submitted_at"] is not None


def test_post_expiry_answer_and_submit_are_rejected(
    admin_client: TestClient,
    db_path: Path,
    student: Callable[[], TestClient],
) -> None:
    quiz = create_quiz(admin_client, "Timed")
    start_session(admin_client, quiz["id"])
    client = joined_student(student, "s-001", "Ada")
    token = client.cookies.get(COOKIE)
    question = client.get("/api/student/quiz").json()["questions"][0]

    backdate_joined_at(db_path, token, timedelta(seconds=600 + 60))

    answer = client.post(
        "/api/student/answer",
        json={"question_id": question["id"], "position": 0},
    )
    assert answer.status_code == 409
    assert "ended" in answer.json()["detail"].lower()

    submit = client.post("/api/student/submit")
    assert submit.status_code == 409
    assert "ended" in submit.json()["detail"].lower()

    quiz_resp = client.get("/api/student/quiz")
    assert quiz_resp.status_code == 409


def test_stop_bulk_finalizes_in_progress_participants_and_leaves_submitters(
    admin_client: TestClient,
    db_path: Path,
    student: Callable[[], TestClient],
) -> None:
    quiz = create_quiz(admin_client, "Capitals")
    texts = correct_texts(quiz)
    start_session(admin_client, quiz["id"])

    submitter = joined_student(student, "s-001", "Ada")
    submitted_token = submitter.cookies.get(COOKIE)
    payload = submitter.get("/api/student/quiz").json()
    answer_questions(submitter, payload["questions"], texts)
    assert submitter.post("/api/student/submit").status_code == 200

    mid_flight = joined_student(student, "s-002", "Grace")
    mid_flight_token = mid_flight.cookies.get(COOKIE)
    payload = mid_flight.get("/api/student/quiz").json()
    answer_questions(mid_flight, payload["questions"], texts, correct_count=2)

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    submitted = participant_row(db_path, submitted_token)
    assert submitted["score"] == 5
    assert submitted["finalized_by"] == "submit"
    assert submitted["submitted_at"] is not None

    finalized = participant_row(db_path, mid_flight_token)
    assert finalized["score"] == 2
    assert finalized["finalized_by"] == "stop"
    assert finalized["submitted_at"] is not None

    assert mid_flight.get("/api/student/state").json() == {"state": "ended"}
    assert submitter.get("/api/student/state").json() == {"state": "submitted"}
    assert mid_flight.post("/api/student/submit").status_code == 409


def test_stopping_with_an_untimed_quiz_still_finalizes_in_progress_students(
    running_session: dict,
    db_path: Path,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student, "s-001", "Ada")
    token = client.cookies.get(COOKIE)
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    row = participant_row(db_path, token)
    assert row["score"] == 0
    assert row["finalized_by"] == "stop"
    assert row["submitted_at"] is not None