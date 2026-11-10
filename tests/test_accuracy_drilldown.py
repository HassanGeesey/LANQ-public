from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from tests.helpers import (
    answer,
    correct_position,
    correct_texts,
    joined_student,
    live,
    student_questions,
    submit,
    wrong_position,
)


def drilldown(client: TestClient, participant_id: int) -> httpx.Response:
    return client.get(f"/api/admin/sessions/participants/{participant_id}")


def roster_id(admin_client: TestClient, student_id: str) -> int:
    roster = live(admin_client).json()["roster"]
    return next(entry["id"] for entry in roster if entry["student_id"] == student_id)


def test_accuracy_chart_is_empty_without_an_active_session(
    admin_client: TestClient,
) -> None:
    data = live(admin_client).json()

    assert data["accuracy"] == []


def test_accuracy_chart_counts_answers_in_canonical_order(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    canonical_ids = [question["id"] for question in capitals_quiz["questions"]]

    thorough = joined_student(student, student_id="s-thorough", name="Thorough")
    thorough_questions = student_questions(thorough)
    for question_id in canonical_ids[:4]:
        position = correct_position(thorough_questions[question_id], texts)
        assert answer(thorough, question_id, position).status_code == 200
    assert submit(thorough).status_code == 200

    partial = joined_student(student, student_id="s-partial", name="Partial")
    partial_questions = student_questions(partial)
    for question_id in canonical_ids[:2]:
        position = wrong_position(partial_questions[question_id], texts)
        assert answer(partial, question_id, position).status_code == 200

    joined_student(student, student_id="s-silent", name="Silent")

    accuracy = live(admin_client).json()["accuracy"]

    assert [entry["question_id"] for entry in accuracy] == canonical_ids
    assert len(accuracy) == len(canonical_ids)
    for entry in accuracy:
        assert entry["participant_count"] == 3

    assert [
        (entry["answered_count"], entry["correct_count"], entry["unanswered"])
        for entry in accuracy
    ] == [
        (2, 1, False),
        (2, 1, False),
        (1, 1, False),
        (1, 1, False),
        (0, 0, True),
    ]


def test_drill_down_requires_authentication(client: TestClient) -> None:
    assert drilldown(client, 1).status_code == 401


def test_drill_down_of_a_submitted_participant_marks_each_answer(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    canonical = capitals_quiz["questions"]
    worker = joined_student(student, student_id="s-ada", name="Ada")
    questions = student_questions(worker)
    for index, question in enumerate(canonical):
        if index == 1:
            position = wrong_position(questions[question["id"]], texts)
        else:
            position = correct_position(questions[question["id"]], texts)
        assert answer(worker, question["id"], position).status_code == 200
    assert submit(worker).status_code == 200

    participant_id = roster_id(admin_client, "s-ada")
    response = drilldown(admin_client, participant_id)

    assert response.status_code == 200
    data = response.json()
    participant = data["participant"]
    assert participant["id"] == participant_id
    assert participant["student_id"] == "s-ada"
    assert participant["name"] == "Ada"
    assert participant["status"] == "submitted"
    assert participant["score"] == 4
    assert participant["joined_at"]
    assert participant["submitted_at"]

    rows = data["questions"]
    assert [row["question_id"] for row in rows] == [
        question["id"] for question in canonical
    ]
    for row, question in zip(rows, canonical):
        assert row["text"] == question["text"]
        assert row["options"] == [
            option["text"] for option in question["options"]
        ]
        assert row["correct_index"] == next(
            index
            for index, option in enumerate(question["options"])
            if option["correct"]
        )
        assert row["correct_option"] == texts[question["text"]]
    assert [row["result"] for row in rows] == [
        "correct",
        "wrong",
        "correct",
        "correct",
        "correct",
    ]
    assert live(admin_client).json()["leaderboard"][0]["id"] == participant_id
    assert rows[1]["chosen_index"] is not None
    assert rows[1]["chosen_index"] != rows[1]["correct_index"]
    assert rows[1]["chosen_option"] != rows[1]["correct_option"]


def test_drill_down_of_an_in_progress_participant_marks_unanswered(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    texts = correct_texts(capitals_quiz)
    canonical = capitals_quiz["questions"]
    worker = joined_student(student, student_id="s-partial", name="Partial")
    questions = student_questions(worker)
    for question in canonical[:2]:
        position = correct_position(questions[question["id"]], texts)
        assert answer(worker, question["id"], position).status_code == 200

    data = drilldown(admin_client, roster_id(admin_client, "s-partial")).json()

    assert data["participant"]["status"] == "in_progress"
    assert data["participant"]["submitted_at"] is None
    assert data["participant"]["score"] == 2
    assert [row["result"] for row in data["questions"]] == [
        "correct",
        "correct",
        "unanswered",
        "unanswered",
        "unanswered",
    ]
    for row in data["questions"][:2]:
        assert row["chosen_index"] == row["correct_index"]
        assert row["chosen_option"] == row["correct_option"]
    for row in data["questions"][2:]:
        assert row["chosen_index"] is None
        assert row["chosen_option"] is None
        assert row["correct_option"]


def test_drill_down_of_a_joined_participant_shows_no_answers(
    admin_client: TestClient,
    running_session: dict,
    student: Callable[[], TestClient],
) -> None:
    joined_student(student, student_id="s-waiting", name="Waiting")

    data = drilldown(admin_client, roster_id(admin_client, "s-waiting")).json()

    assert data["participant"]["status"] == "joined"
    assert [row["result"] for row in data["questions"]] == ["unanswered"] * 5


def test_drill_down_is_404_for_unknown_or_foreign_participants(
    admin_client: TestClient,
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    joined_student(student, student_id="s-old", name="Old")
    stale_id = roster_id(admin_client, "s-old")

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200
    restarted = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    )
    assert restarted.status_code == 201

    assert drilldown(admin_client, stale_id).status_code == 404
    assert drilldown(admin_client, 999999).status_code == 404


def test_admin_page_renders_the_accuracy_chart(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    for element_id in ("accuracy-chart", "accuracy-empty"):
        assert f'id="{element_id}"' in response.text, element_id


def test_admin_page_renders_the_drilldown_panel(client: TestClient) -> None:
    response = client.get("/admin")

    assert response.status_code == 200
    for element_id in (
        "drilldown",
        "drilldown-title",
        "drilldown-questions",
        "drilldown-close-button",
    ):
        assert f'id="{element_id}"' in response.text, element_id
