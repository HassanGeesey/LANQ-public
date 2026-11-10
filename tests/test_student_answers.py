from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

from tests.helpers import joined_student


def answer(client: TestClient, question_id: int, position: int) -> httpx.Response:
    return client.post(
        "/api/student/answer",
        json={"question_id": question_id, "position": position},
    )


def submit(client: TestClient) -> httpx.Response:
    return client.post("/api/student/submit")


def correct_texts(quiz: dict) -> dict[str, str]:
    return {
        question["text"]: next(
            option["text"] for option in question["options"] if option["correct"]
        )
        for question in quiz["questions"]
    }


def answer_every(
    client: TestClient, choose: Callable[[dict], int]
) -> None:
    payload = client.get("/api/student/quiz").json()
    for question in payload["questions"]:
        response = answer(client, question["id"], choose(question))
        assert response.status_code == 200, response.text


def test_a_fresh_join_starts_with_no_saved_answers(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)

    quiz = client.get("/api/student/quiz").json()

    assert quiz["answers"] == {}


def test_a_choice_is_autosaved_and_restored_in_display_order_after_a_reload(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)
    quiz = client.get("/api/student/quiz").json()
    question = quiz["questions"][3]
    chosen = question["options"][2]

    response = answer(client, question["id"], 2)

    assert response.status_code == 200
    reloaded = client.get("/api/student/quiz").json()
    assert reloaded["answers"] == {str(question["id"]): 2}
    restored = next(
        item
        for item in reloaded["questions"]
        if item["id"] == question["id"]
    )
    assert restored["options"][2] == chosen


def test_choosing_another_option_overwrites_the_saved_answer(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)
    question = client.get("/api/student/quiz").json()["questions"][0]

    answer(client, question["id"], 1)
    answer(client, question["id"], 3)

    reloaded = client.get("/api/student/quiz").json()
    assert reloaded["answers"] == {str(question["id"]): 3}


def test_answering_without_joining_is_rejected(
    student: Callable[[], TestClient]
) -> None:
    client = student()

    response = answer(client, 1, 0)

    assert response.status_code == 401


def test_an_unknown_question_is_rejected(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)

    response = answer(client, 999_999, 0)

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == "Answer validation failed"
    assert any(
        error["field"] == "question_id"
        and "unknown" in error["message"].lower()
        for error in detail["errors"]
    ), detail


def test_an_out_of_range_position_is_rejected(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)
    question = client.get("/api/student/quiz").json()["questions"][0]

    too_high = answer(client, question["id"], len(question["options"]))
    too_low = answer(client, question["id"], -1)

    assert too_high.status_code == 422
    assert too_low.status_code == 422
    for response in (too_high, too_low):
        detail = response.json()["detail"]
        assert detail["message"] == "Answer validation failed"
        assert any(
            error["field"] == "position"
            and "invalid" in error["message"].lower()
            for error in detail["errors"]
        ), detail


def test_submitting_without_joining_is_rejected(
    student: Callable[[], TestClient]
) -> None:
    client = student()

    response = submit(client)

    assert response.status_code == 401


def test_submitting_all_correct_choices_scores_full_marks(
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    texts = correct_texts(capitals_quiz)
    answer_every(
        client, lambda question: question["options"].index(texts[question["text"]])
    )

    response = submit(client)

    assert response.status_code == 200
    assert response.json() == {"state": "submitted", "score": 5}


def test_submitting_all_wrong_choices_scores_zero(
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    texts = correct_texts(capitals_quiz)
    answer_every(
        client,
        lambda question: next(
            i
            for i, option in enumerate(question["options"])
            if option != texts[question["text"]]
        ),
    )

    response = submit(client)

    assert response.status_code == 200
    assert response.json() == {"state": "submitted", "score": 0}


def test_mixed_answers_score_partially(
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    texts = correct_texts(capitals_quiz)
    payload = client.get("/api/student/quiz").json()
    for index, question in enumerate(payload["questions"]):
        if index < 2:
            position = question["options"].index(texts[question["text"]])
        else:
            position = next(
                i
                for i, option in enumerate(question["options"])
                if option != texts[question["text"]]
            )
        assert answer(client, question["id"], position).status_code == 200

    response = submit(client)

    assert response.json() == {"state": "submitted", "score": 2}


def test_a_second_submit_returns_the_same_submitted_state_without_changes(
    running_session: dict,
    capitals_quiz: dict,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    texts = correct_texts(capitals_quiz)
    answer_every(
        client, lambda question: question["options"].index(texts[question["text"]])
    )

    first = submit(client)
    second = submit(client)
    third = submit(client)

    assert first.status_code == 200
    assert first.json() == {"state": "submitted", "score": 5}
    assert second.json() == first.json()
    assert third.json() == first.json()


def test_answering_after_submission_is_rejected_with_409(
    running_session: dict, student: Callable[[], TestClient]
) -> None:
    client = joined_student(student)
    question = client.get("/api/student/quiz").json()["questions"][0]
    assert submit(client).status_code == 200

    response = answer(client, question["id"], 0)

    assert response.status_code == 409
    assert "already submitted" in response.json()["detail"].lower()


def test_submitting_after_the_session_stops_mid_flight_is_rejected(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = submit(client)

    assert response.status_code == 409
    assert "ended" in response.json()["detail"].lower()


def test_answering_after_the_session_stops_mid_flight_is_rejected(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    question = client.get("/api/student/quiz").json()["questions"][0]
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = answer(client, question["id"], 0)

    assert response.status_code == 409
    assert "ended" in response.json()["detail"].lower()


def test_state_reports_submitted_after_submitting_and_stays_submitted(
    running_session: dict,
    admin_client: TestClient,
    student: Callable[[], TestClient],
) -> None:
    client = joined_student(student)
    assert submit(client).status_code == 200

    assert client.get("/api/student/state").json() == {"state": "submitted"}

    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    assert client.get("/api/student/state").json() == {"state": "submitted"}
    assert client.get("/api/student/quiz").status_code == 409