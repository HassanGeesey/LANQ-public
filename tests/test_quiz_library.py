import sqlite3
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from lanq.main import create_app


def quiz_payload() -> dict:
    return {
        "title": "Photosynthesis",
        "questions": [
            {
                "text": "What does chlorophyll absorb?",
                "options": [
                    {"text": "Green light", "correct": False},
                    {"text": "Red and blue light", "correct": True},
                    {"text": "Sound waves", "correct": False},
                ],
            }
        ],
    }


def test_quiz_endpoints_reject_unauthenticated_access(client: TestClient) -> None:
    requests = [
        ("GET", "/api/admin/quizzes"),
        ("POST", "/api/admin/quizzes"),
        ("GET", "/api/admin/quizzes/1"),
        ("GET", "/api/admin/quizzes/1/preview"),
        ("PUT", "/api/admin/quizzes/1"),
        ("DELETE", "/api/admin/quizzes/1"),
    ]
    for method, path in requests:
        response = client.request(method, path, json=quiz_payload())
        assert response.status_code == 401, f"{method} {path}"

    client.cookies.set("lanq_session", "not-a-real-token")
    for method, path in requests:
        response = client.request(method, path, json=quiz_payload())
        assert response.status_code == 401, f"{method} {path}"


def test_create_read_and_list_quiz_round_trip(admin_client: TestClient) -> None:
    created = admin_client.post("/api/admin/quizzes", json=quiz_payload())
    assert created.status_code == 201
    body = created.json()
    assert isinstance(body["id"], int)
    assert body["title"] == "Photosynthesis"
    assert body["time_limit_seconds"] is None
    assert isinstance(body["created_at"], str)
    assert len(body["questions"]) == 1
    question = body["questions"][0]
    assert isinstance(question["id"], int)
    assert question["text"] == "What does chlorophyll absorb?"
    assert question["options"] == [
        {"text": "Green light", "correct": False},
        {"text": "Red and blue light", "correct": True},
        {"text": "Sound waves", "correct": False},
    ]

    fetched = admin_client.get(f"/api/admin/quizzes/{body['id']}")
    assert fetched.status_code == 200
    assert fetched.json() == body

    listing = admin_client.get("/api/admin/quizzes")
    assert listing.status_code == 200
    assert listing.json() == [
        {
            "id": body["id"],
            "title": "Photosynthesis",
            "time_limit_seconds": None,
            "created_at": body["created_at"],
            "question_count": 1,
        }
    ]


def make_question(
    text: str, option_texts: list[str], correct: list[int]
) -> dict:
    return {
        "text": text,
        "options": [
            {"text": option_text, "correct": index in correct}
            for index, option_text in enumerate(option_texts)
        ],
    }


def quiz_with(**overrides: object) -> dict:
    payload = quiz_payload()
    payload.update(overrides)
    return payload


def validation_detail(response: httpx.Response, message: str) -> list[dict]:
    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["message"] == message
    return detail["errors"]


def assert_rejected(
    admin_client: TestClient, payload: dict, field: str, fragment: str
) -> None:
    response = admin_client.post("/api/admin/quizzes", json=payload)
    errors = validation_detail(response, "Quiz validation failed")
    matching = [error for error in errors if error["field"] == field]
    assert matching, f"no error reported for {field!r}: {errors}"
    assert fragment.lower() in matching[0]["message"].lower()
    assert admin_client.get("/api/admin/quizzes").json() == []


@pytest.mark.parametrize(
    ("payload", "field", "fragment"),
    [
        pytest.param(
            quiz_with(title="   "),
            "title",
            "must not be empty",
            id="empty title",
        ),
        pytest.param(
            quiz_with(questions=[make_question("", ["a", "b"], [0])]),
            "questions[0].text",
            "must not be empty",
            id="empty question text",
        ),
        pytest.param(
            quiz_with(
                questions=[make_question("Q", ["yes", "   "], [1])]
            ),
            "questions[0].options[1].text",
            "must not be empty",
            id="empty option text",
        ),
        pytest.param(
            quiz_with(questions=[make_question("Q", ["only one"], [0])]),
            "questions[0].options",
            "between 2 and 6",
            id="too few options",
        ),
        pytest.param(
            quiz_with(
                questions=[
                    make_question("Q", ["a", "b", "c", "d", "e", "f", "g"], [0])
                ]
            ),
            "questions[0].options",
            "between 2 and 6",
            id="too many options",
        ),
        pytest.param(
            quiz_with(questions=[make_question("Q", ["a", "b"], [])]),
            "questions[0].options",
            "exactly one option",
            id="zero correct options",
        ),
        pytest.param(
            quiz_with(questions=[make_question("Q", ["a", "b", "c"], [0, 2])]),
            "questions[0].options",
            "exactly one option",
            id="multiple correct options",
        ),
    ],
)
def test_quiz_content_validation(
    admin_client: TestClient, payload: dict, field: str, fragment: str
) -> None:
    assert_rejected(admin_client, payload, field, fragment)


def test_malformed_payloads_share_the_same_error_shape(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/admin/quizzes",
        json={"title": "Q", "questions": [{"text": "Missing options"}]},
    )
    errors = validation_detail(response, "Validation failed")
    assert any(
        error["field"] == "questions[0].options"
        and "required" in error["message"].lower()
        for error in errors
    ), errors
    assert admin_client.get("/api/admin/quizzes").json() == []


def test_preview_has_no_persistence_and_uses_only_local_assets(
    admin_client,
) -> None:
    quiz = admin_client.post(
        "/api/admin/quizzes",
        json={
            "title": "Preview quiz",
            "questions": [
                {
                    "text": "Pick the right color",
                    "options": [
                        {"text": "Blue", "correct": True},
                        {"text": "Green", "correct": False},
                        {"text": "Red", "correct": False},
                    ],
                }
            ],
        },
    ).json()

    db_path = admin_client.app.state.db_path
    with sqlite3.connect(db_path) as conn:
        before_participants = conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0]
        before_answers = conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]

    response = admin_client.get(f"/api/admin/quizzes/{quiz['id']}/preview")
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "Preview quiz"
    assert body["answers"] == {}
    assert {question["id"] for question in body["questions"]} == {
        question["id"] for question in quiz["questions"]
    }
    assert body["questions"][0]["options"]
    assert body["questions"][0]["options"] == [
        "Blue",
        "Green",
        "Red",
    ] or body["questions"][0]["options"] == [
        "Blue",
        "Red",
        "Green",
    ] or body["questions"][0]["options"] == [
        "Green",
        "Blue",
        "Red",
    ] or body["questions"][0]["options"] == [
        "Green",
        "Red",
        "Blue",
    ] or body["questions"][0]["options"] == [
        "Red",
        "Blue",
        "Green",
    ] or body["questions"][0]["options"] == [
        "Red",
        "Green",
        "Blue",
    ]

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM participants").fetchone()[0] == before_participants
        assert conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0] == before_answers

    student_html = Path("static/student/index.html").read_text(encoding="utf-8")
    admin_html = Path("static/admin/index.html").read_text(encoding="utf-8")
    for source in (student_html, admin_html):
        assert "http://" not in source and "https://" not in source
        assert "cdn" not in source.lower()


def three_question_quiz() -> dict:
    return {
        "title": "Capitals",
        "questions": [
            make_question("Q1", ["Paris", "Rome"], [0]),
            make_question("Q2", ["Tokyo", "Seoul"], [0]),
            make_question("Q3", ["Cairo", "Nairobi"], [1]),
        ],
    }


def test_update_edits_reorders_adds_and_removes_questions(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()
    first, second, third = created["questions"]

    response = admin_client.put(
        f"/api/admin/quizzes/{created['id']}",
        json={
            "title": "World capitals",
            "time_limit_seconds": 600,
            "questions": [
                third,
                {**first, "text": "Q1 edited"},
                make_question("Q4", ["Lima", "Bogota"], [0]),
            ],
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["title"] == "World capitals"
    assert body["time_limit_seconds"] == 600
    assert [question["text"] for question in body["questions"]] == [
        "Q3",
        "Q1 edited",
        "Q4",
    ]
    assert body["questions"][0]["id"] == third["id"]
    assert body["questions"][1]["id"] == first["id"]
    assert isinstance(body["questions"][2]["id"], int)
    assert second["id"] not in {
        question["id"] for question in body["questions"]
    }

    fetched = admin_client.get(f"/api/admin/quizzes/{created['id']}")
    assert fetched.json() == body


def test_update_rejects_invalid_content_and_leaves_the_quiz_unchanged(
    admin_client: TestClient,
) -> None:
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()
    before = admin_client.get(f"/api/admin/quizzes/{created['id']}").json()

    response = admin_client.put(
        f"/api/admin/quizzes/{created['id']}",
        json={
            "title": "Broken",
            "questions": [make_question("Only one", ["solo"], [0])],
        },
    )
    assert response.status_code == 422
    errors = validation_detail(response, "Quiz validation failed")
    assert any(error["field"] == "questions[0].options" for error in errors)

    assert admin_client.get(f"/api/admin/quizzes/{created['id']}").json() == before


def test_update_rejects_question_ids_from_elsewhere(
    admin_client: TestClient,
) -> None:
    other = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()
    before = admin_client.get(f"/api/admin/quizzes/{created['id']}").json()
    foreign_id = other["questions"][0]["id"]

    response = admin_client.put(
        f"/api/admin/quizzes/{created['id']}",
        json={
            "title": "Capitals",
            "questions": [
                {"id": foreign_id, **make_question("Stolen", ["a", "b"], [0])}
            ],
        },
    )
    assert response.status_code == 422
    errors = validation_detail(response, "Quiz validation failed")
    assert any(
        error["field"] == "questions[0].id"
        and "does not belong" in error["message"]
        for error in errors
    ), errors

    assert admin_client.get(f"/api/admin/quizzes/{created['id']}").json() == before


def test_update_rejects_a_repeated_question_id(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()
    before = admin_client.get(f"/api/admin/quizzes/{created['id']}").json()
    question = created["questions"][0]

    response = admin_client.put(
        f"/api/admin/quizzes/{created['id']}",
        json={"title": "Capitals", "questions": [question, question]},
    )
    assert response.status_code == 422
    errors = validation_detail(response, "Quiz validation failed")
    assert any(
        error["field"] == "questions[1].id"
        and "repeated" in error["message"]
        for error in errors
    ), errors

    assert admin_client.get(f"/api/admin/quizzes/{created['id']}").json() == before


def test_delete_removes_the_quiz_from_the_library(admin_client: TestClient) -> None:
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()

    response = admin_client.delete(f"/api/admin/quizzes/{created['id']}")
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert admin_client.get("/api/admin/quizzes").json() == []
    assert (
        admin_client.get(f"/api/admin/quizzes/{created['id']}").status_code
        == 404
    )


def test_unknown_quiz_ids_return_404(admin_client: TestClient) -> None:
    assert admin_client.get("/api/admin/quizzes/9999").status_code == 404
    assert (
        admin_client.put(
            "/api/admin/quizzes/9999",
            json={"title": "Ghost", "questions": []},
        ).status_code
        == 404
    )
    assert admin_client.delete("/api/admin/quizzes/9999").status_code == 404


def test_quizzes_survive_a_restart(
    admin_client: TestClient, db_path: Path
) -> None:
    created = admin_client.post(
        "/api/admin/quizzes", json=three_question_quiz()
    ).json()

    with TestClient(create_app(db_path=db_path)) as restarted:
        login = restarted.post(
            "/api/admin/login",
            json={"username": "ms.Rivera", "password": "correct horse"},
        )
        assert login.status_code == 200
        listing = restarted.get("/api/admin/quizzes")
        assert listing.status_code == 200
        assert [quiz["id"] for quiz in listing.json()] == [created["id"]]
        fetched = restarted.get(f"/api/admin/quizzes/{created['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == created


def test_saved_text_is_trimmed(admin_client: TestClient) -> None:
    response = admin_client.post(
        "/api/admin/quizzes",
        json={
            "title": "  Photosynthesis  ",
            "questions": [
                {
                    "text": "  What does chlorophyll absorb?  ",
                    "options": [
                        {"text": "  Green light  ", "correct": True},
                        {"text": "Sound waves", "correct": False},
                    ],
                }
            ],
        },
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Photosynthesis"
    assert body["questions"][0]["text"] == "What does chlorophyll absorb?"
    assert body["questions"][0]["options"][0]["text"] == "Green light"


def test_a_quiz_can_be_saved_with_no_questions_yet(
    admin_client: TestClient,
) -> None:
    response = admin_client.post(
        "/api/admin/quizzes",
        json={"title": "Work in progress", "questions": []},
    )
    assert response.status_code == 201
    body = response.json()
    assert body["title"] == "Work in progress"
    assert body["questions"] == []
    assert admin_client.get("/api/admin/quizzes").json()[0]["question_count"] == 0
