import json
from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.helpers import joined_student


def test_quiz_requires_a_joined_identity(student: Callable[[], TestClient]) -> None:
    client = student()

    response = client.get("/api/student/quiz")

    assert response.status_code == 401


def test_the_payload_is_shuffled_and_never_marks_the_correct_option(
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student, "s-001", "Ada")

    response = client.get("/api/student/quiz")

    assert response.status_code == 200
    payload = response.json()
    assert payload["title"] == capitals_quiz["title"]
    assert payload["time_limit_seconds"] is None
    assert "correct" not in response.text.lower()

    questions = payload["questions"]
    assert len(questions) == len(capitals_quiz["questions"])
    assert len({question["id"] for question in questions}) == len(questions)

    canonical = {
        question["text"]: sorted(
            option["text"] for option in question["options"]
        )
        for question in capitals_quiz["questions"]
    }
    for question in questions:
        assert set(question) == {"id", "text", "options"}
        assert isinstance(question["id"], int)
        assert len(question["options"]) == 4
        assert all(isinstance(option, str) for option in question["options"])
        assert sorted(question["options"]) == canonical[question["text"]]


def test_the_shuffle_is_stable_across_repeated_fetches(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student, "s-001", "Ada")

    first = client.get("/api/student/quiz").json()
    second = client.get("/api/student/quiz").json()
    third = client.get("/api/student/quiz").json()

    def without_clock(payload: dict) -> dict:
        return {key: value for key, value in payload.items() if key != "server_time"}

    assert without_clock(first) == without_clock(second) == without_clock(third)


def test_participants_get_different_arrangements(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    arrangements = set()
    for index in range(4):
        client = joined_student(student, f"s-{index}", f"Student {index}")
        questions = client.get("/api/student/quiz").json()["questions"]
        arrangements.add(json.dumps(questions, sort_keys=True))

    assert len(arrangements) > 1


def test_quiz_is_unavailable_after_the_session_stops(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student, "s-001", "Ada")

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = client.get("/api/student/quiz")
    assert response.status_code == 409
    assert "ended" in response.json()["detail"].lower()


def test_a_stale_identity_cannot_fetch_the_next_sessions_quiz(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student, "s-001", "Ada")
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
    assert (
        admin_client.post(
            "/api/admin/sessions", json={"quiz_id": next_quiz.json()["id"]}
        ).status_code
        == 201
    )

    response = client.get("/api/student/quiz")

    assert response.status_code == 409
