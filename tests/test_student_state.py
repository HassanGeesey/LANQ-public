from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.helpers import join


def test_state_is_join_when_a_session_runs_and_nobody_has_joined(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()

    assert client.get("/api/student/state").json() == {"state": "join"}


def test_state_stays_quiz_across_refreshes(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()
    assert join(client).status_code == 201

    for _ in range(3):
        assert client.get("/api/student/state").json() == {"state": "quiz"}


def test_a_stopped_session_shows_ended_to_mid_flight_students_and_hides_the_join_page(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    joined = student()
    assert join(joined).status_code == 201

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    assert joined.get("/api/student/state").json() == {"state": "ended"}

    newcomer = student()
    assert newcomer.get("/api/student/state").json() == {"state": "no_quiz"}
    assert join(newcomer).status_code == 409


def test_a_stale_cookie_falls_back_to_the_join_form_when_a_new_session_starts(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = student()
    assert join(client, student_id="s-001", name="Ada").status_code == 201
    stale_token = client.cookies.get("lanq_participant")

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200
    next_quiz = admin_client.post(
        "/api/admin/quizzes",
        json={
            "title": "Next quiz",
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
    assert next_quiz.status_code == 201
    started = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": next_quiz.json()["id"]}
    )
    assert started.status_code == 201

    assert client.get("/api/student/state").json() == {"state": "join"}

    rejoin = join(client, student_id="s-002", name="Grace")
    assert rejoin.status_code == 201
    assert client.cookies.get("lanq_participant") != stale_token
    assert client.get("/api/student/state").json() == {"state": "quiz"}
    assert client.get("/api/student/quiz").status_code == 200
