from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from tests.helpers import (
    answer,
    answer_every,
    correct_position,
    correct_texts,
    joined_student,
    live,
    submit,
    wrong_position,
)


def history(client: TestClient) -> list[dict]:
    response = client.get("/api/admin/sessions/history")
    assert response.status_code == 200, response.text
    return response.json()


def dashboard(client: TestClient, session_id: int) -> httpx.Response:
    return client.get(f"/api/admin/sessions/{session_id}/dashboard")


def drilldown(
    client: TestClient, session_id: int, participant_id: int
) -> httpx.Response:
    return client.get(
        f"/api/admin/sessions/{session_id}/participants/{participant_id}"
    )


def delete_session(client: TestClient, session_id: int) -> httpx.Response:
    return client.delete(f"/api/admin/sessions/{session_id}")


def roster_participant(admin_client: TestClient, student_id: str) -> int:
    return next(
        entry["id"]
        for entry in live(admin_client).json()["roster"]
        if entry["student_id"] == student_id
    )


def test_history_requires_authentication(client: TestClient) -> None:
    assert client.get("/api/admin/sessions/history").status_code == 401
    assert dashboard(client, 1).status_code == 401
    assert drilldown(client, 1, 1).status_code == 401
    assert delete_session(client, 1).status_code == 401
    client.cookies.set("lanq_session", "not-a-real-token")
    assert client.get("/api/admin/sessions/history").status_code == 401
    assert dashboard(client, 1).status_code == 401
    assert drilldown(client, 1, 1).status_code == 401
    assert delete_session(client, 1).status_code == 401


def test_history_is_empty_before_any_session(admin_client: TestClient) -> None:
    assert history(admin_client) == []


def test_history_lists_sessions_newest_first_with_their_counts(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    first = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    ).json()
    joined_student(student, student_id="s-one", name="One")
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    second = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    ).json()
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    entries = history(admin_client)

    assert [entry["id"] for entry in entries] == [second["id"], first["id"]]
    top, bottom = entries
    for entry in (top, bottom):
        assert entry["title"] == "Capitals"
        assert entry["status"] == "ended"
        assert entry["started_at"]
        assert entry["ended_at"]
        assert entry["question_count"] == 5
    assert first["id"] == bottom["id"]
    assert bottom["participant_count"] == 1
    assert second["id"] == top["id"]
    assert top["participant_count"] == 0


def test_history_includes_the_active_session(
    admin_client: TestClient, running_session: dict
) -> None:
    [entry] = history(admin_client)

    assert entry["id"] == running_session["id"]
    assert entry["status"] == "active"
    assert entry["ended_at"] is None


def test_historical_dashboard_matches_the_live_dashboard_for_the_same_session(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    done = joined_student(student, student_id="s-done", name="Done")
    answer_every(done, lambda q: correct_position(q, texts))
    assert submit(done).status_code == 200

    mixed = joined_student(student, student_id="s-mixed", name="Mixed")
    questions = {
        question["id"]: question
        for question in mixed.get("/api/student/quiz").json()["questions"]
    }
    for index, question in enumerate(capitals_quiz["questions"]):
        if index % 2:
            position = wrong_position(questions[question["id"]], texts)
        else:
            position = correct_position(questions[question["id"]], texts)
        assert answer(mixed, question["id"], position).status_code == 200
    assert submit(mixed).status_code == 200

    live_before = live(admin_client).json()
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    historical = dashboard(admin_client, running_session["id"])
    assert historical.status_code == 200
    body = historical.json()

    assert body["roster"] == live_before["roster"]
    assert body["leaderboard"] == live_before["leaderboard"]
    assert body["accuracy"] == live_before["accuracy"]
    session = body["session"]
    assert session["id"] == running_session["id"]
    assert session["status"] == "ended"
    assert session["ended_at"]
    assert session["title"] == "Capitals"
    assert session["question_count"] == 5


def test_historical_dashboard_holds_finalized_results_for_early_stoppers(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    done = joined_student(student, student_id="s-done", name="Done")
    answer_every(done, lambda q: correct_position(q, texts))
    assert submit(done).status_code == 200

    working = joined_student(student, student_id="s-working", name="Working")
    questions = {
        question["id"]: question
        for question in working.get("/api/student/quiz").json()["questions"]
    }
    for question in capitals_quiz["questions"][:2]:
        assert answer(
            working, question["id"], correct_position(questions[question["id"]], texts)
        ).status_code == 200

    joined_student(student, student_id="s-waiting", name="Waiting")
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    body = dashboard(admin_client, running_session["id"]).json()

    roster = {entry["student_id"]: entry for entry in body["roster"]}
    assert {entry["status"] for entry in body["roster"]} == {"submitted"}
    assert roster["s-done"]["score"] == 5
    assert roster["s-working"]["score"] == 2
    assert roster["s-waiting"]["score"] == 0
    assert [entry["student_id"] for entry in body["leaderboard"]] == [
        "s-done",
        "s-working",
        "s-waiting",
    ]
    accuracy = body["accuracy"]
    assert [entry["participant_count"] for entry in accuracy] == [3] * 5


def test_historical_drill_down_renders_the_same_participant(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    worker = joined_student(student, student_id="s-ada", name="Ada")
    questions = {
        question["id"]: question
        for question in worker.get("/api/student/quiz").json()["questions"]
    }
    for index, question in enumerate(capitals_quiz["questions"]):
        position = (
            wrong_position(questions[question["id"]], texts)
            if index == 1
            else correct_position(questions[question["id"]], texts)
        )
        assert answer(worker, question["id"], position).status_code == 200
    assert submit(worker).status_code == 200
    participant_id = roster_participant(admin_client, "s-ada")

    live_drilldown = admin_client.get(
        f"/api/admin/sessions/participants/{participant_id}"
    ).json()
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = drilldown(admin_client, running_session["id"], participant_id)

    assert response.status_code == 200
    body = response.json()
    assert body["participant"] == live_drilldown["participant"]
    assert body["questions"] == live_drilldown["questions"]
    assert [row["result"] for row in body["questions"]] == [
        "correct",
        "wrong",
        "correct",
        "correct",
        "correct",
    ]


def test_session_dashboard_and_drill_down_are_404_for_unknown_sessions(
    admin_client: TestClient,
) -> None:
    assert dashboard(admin_client, 999999).status_code == 404
    assert drilldown(admin_client, 999999, 1).status_code == 404
    assert delete_session(admin_client, 999999).status_code == 404


def test_historical_drill_down_rejects_participants_of_other_sessions(
    admin_client: TestClient,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    first = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    ).json()
    joined_student(student, student_id="s-old", name="Old")
    participant_id = roster_participant(admin_client, "s-old")
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    assert drilldown(admin_client, first["id"], participant_id).status_code == 200
    assert drilldown(admin_client, 999999, participant_id).status_code == 404


def test_deleting_the_active_session_is_refused(
    admin_client: TestClient, running_session: dict
) -> None:
    response = delete_session(admin_client, running_session["id"])

    assert response.status_code == 409
    assert "stop" in response.json()["detail"].lower()
    assert history(admin_client)[0]["status"] == "active"


def test_deleting_a_session_cascades_to_participants_and_answers(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    worker = joined_student(student, student_id="s-ada", name="Ada")
    answer_every(worker, lambda q: correct_position(q, texts))
    assert submit(worker).status_code == 200
    participant_id = roster_participant(admin_client, "s-ada")
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200
    session_id = running_session["id"]

    response = delete_session(admin_client, session_id)

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert session_id not in {
        entry["id"] for entry in history(admin_client)
    }
    assert dashboard(admin_client, session_id).status_code == 404
    assert drilldown(admin_client, session_id, participant_id).status_code == 404
    assert (
        admin_client.get(f"/api/admin/sessions/{session_id}/export.csv").status_code
        == 404
    )
    assert delete_session(admin_client, session_id).status_code == 404
    assert worker.get("/api/student/state").json()["state"] == "no_quiz"


def test_deleting_a_session_leaves_the_quiz_in_the_library(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
) -> None:
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = delete_session(admin_client, running_session["id"])

    assert response.status_code == 200
    library = admin_client.get("/api/admin/quizzes").json()
    assert capitals_quiz["id"] in {quiz["id"] for quiz in library}
    restarted = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    )
    assert restarted.status_code == 201


def test_admin_page_renders_the_history_view(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    for element_id in (
        "history-tab",
        "history-empty",
        "history-table",
        "history-body",
    ):
        assert f'id="{element_id}"' in response.text, element_id