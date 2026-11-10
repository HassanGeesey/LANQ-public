from collections.abc import Callable

import httpx
from fastapi.testclient import TestClient

COOKIE = "lanq_participant"


def live(client: TestClient) -> httpx.Response:
    return client.get("/api/admin/sessions/live")


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


def correct_position(question: dict, texts: dict[str, str]) -> int:
    return question["options"].index(texts[question["text"]])


def wrong_position(question: dict, texts: dict[str, str]) -> int:
    return next(
        index
        for index, option in enumerate(question["options"])
        if option != texts[question["text"]]
    )


def student_questions(client: TestClient) -> dict[int, dict]:
    payload = client.get("/api/student/quiz").json()
    return {question["id"]: question for question in payload["questions"]}


def answer_every(
    client: TestClient, choose: Callable[[dict], int]
) -> None:
    for question in student_questions(client).values():
        response = answer(client, question["id"], choose(question))
        assert response.status_code == 200, response.text


def joined_student(
    student: Callable[[], TestClient], student_id: str = "s-001", name: str = "Ada"
) -> TestClient:
    client = student()
    response = join(client, student_id=student_id, name=name)
    assert response.status_code == 201, response.text
    return client


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


def quiz_payload(title: str = "Capitals") -> dict:
    return {
        "title": title,
        "time_limit_seconds": 600,
        "questions": [
            make_question("Q1", ["Paris", "Rome", "Berlin", "Madrid"], [0]),
            make_question("Q2", ["Tokyo", "Seoul", "Osaka", "Kyoto"], [1]),
            make_question("Q3", ["Cairo", "Nairobi", "Accra", "Lagos"], [2]),
            make_question("Q4", ["Ottawa", "Toronto", "Montreal", "Vancouver"], [0]),
            make_question("Q5", ["Brasilia", "Rio", "Sao Paulo", "Salvador"], [3]),
        ],
    }


def create_quiz(admin_client: TestClient, title: str = "Capitals") -> dict:
    response = admin_client.post(
        "/api/admin/quizzes", json=quiz_payload(title)
    )
    assert response.status_code == 201
    return response.json()


def start_session(admin_client: TestClient, quiz_id: int) -> dict:
    response = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": quiz_id}
    )
    assert response.status_code == 201, response.text
    return response.json()


def join(client: TestClient, **fields: str) -> httpx.Response:
    payload = {"student_id": "s-001", "name": "Ada"}
    payload.update(fields)
    return client.post("/api/student/join", json=payload)
