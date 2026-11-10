from collections.abc import Callable

from fastapi.testclient import TestClient

from tests.helpers import COOKIE, join


def test_join_requires_a_student_id_and_a_name(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()

    missing_id = client.post("/api/student/join", json={"name": "Ada"})
    assert missing_id.status_code == 422
    detail = missing_id.json()["detail"]
    assert detail["message"] == "Validation failed"
    assert any(
        error["field"] == "student_id" for error in detail["errors"]
    ), detail

    missing_name = client.post("/api/student/join", json={"student_id": "s1"})
    assert missing_name.status_code == 422
    detail = missing_name.json()["detail"]
    assert detail["message"] == "Validation failed"
    assert any(error["field"] == "name" for error in detail["errors"]), detail

    blank_id = join(client, student_id="   ")
    assert blank_id.status_code == 422
    detail = blank_id.json()["detail"]
    assert detail["message"] == "Join validation failed"
    matching = [
        error for error in detail["errors"] if error["field"] == "student_id"
    ]
    assert matching and "must not be empty" in matching[0]["message"], detail

    blank_name = join(client, name="  ")
    assert blank_name.status_code == 422
    detail = blank_name.json()["detail"]
    assert detail["message"] == "Join validation failed"
    matching = [
        error for error in detail["errors"] if error["field"] == "name"
    ]
    assert matching and "must not be empty" in matching[0]["message"], detail
    assert client.cookies.get(COOKIE) is None


def test_join_creates_a_participant_with_a_cookie_identity(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()

    response = join(client)

    assert response.status_code == 201
    assert response.json() == {"state": "quiz"}
    assert client.cookies.get(COOKIE)
    assert client.get("/api/student/state").json() == {"state": "quiz"}


def test_duplicate_student_ids_and_names_are_allowed(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    first = student()
    second = student()

    first_response = join(first, student_id="42", name="Ada")
    second_response = join(second, student_id="42", name="Ada")

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert first.cookies.get(COOKIE) != second.cookies.get(COOKIE)
    assert first.get("/api/student/state").json() == {"state": "quiz"}
    assert second.get("/api/student/state").json() == {"state": "quiz"}


def test_rejoining_with_the_same_identity_keeps_the_same_attempt(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()
    first = join(client, student_id="s-001", name="Ada")
    assert first.status_code == 201
    token = client.cookies.get(COOKIE)

    again = join(client, student_id="s-001", name="Ada")

    assert again.status_code == 200
    assert again.json() == {"state": "quiz"}
    assert client.cookies.get(COOKIE) == token


def test_joining_with_a_different_identity_switches_attempt(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = student()
    join(client, student_id="s-001", name="Ada")
    first_token = client.cookies.get(COOKIE)

    response = join(client, student_id="s-002", name="Bob")

    assert response.status_code == 201
    assert response.json() == {"state": "quiz"}
    assert client.cookies.get(COOKIE) != first_token
    assert client.get("/api/student/state").json() == {"state": "quiz"}


def test_join_is_refused_when_no_quiz_is_running(
    student: Callable[[], TestClient]
) -> None:
    client = student()

    response = join(client)

    assert response.status_code == 409
    assert "no active quiz" in response.json()["detail"].lower()
    assert client.cookies.get(COOKIE) is None


def test_join_is_refused_after_the_session_is_stopped(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = join(student())

    assert response.status_code == 409
    assert "no active quiz" in response.json()["detail"].lower()
