from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from lanq.main import create_app
from tests.helpers import make_question


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def app(db_path: Path) -> FastAPI:
    return create_app(db_path=db_path)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def setup_teacher(client: TestClient) -> Callable[..., None]:
    def _setup_teacher(
        username: str = "ms.Rivera", password: str = "correct horse"
    ) -> None:
        response = client.post(
            "/api/admin/setup", json={"username": username, "password": password}
        )
        assert response.status_code == 201

    return _setup_teacher


@pytest.fixture
def admin_client(client: TestClient, setup_teacher: Callable[..., None]) -> TestClient:
    setup_teacher()
    response = client.post(
        "/api/admin/login",
        json={"username": "ms.Rivera", "password": "correct horse"},
    )
    assert response.status_code == 200
    return client


@pytest.fixture
def capitals_quiz(admin_client: TestClient) -> dict:
    """A five-question quiz, big enough that shuffles almost never collide."""
    payload = {
        "title": "Capitals",
        "time_limit_seconds": None,
        "questions": [
            make_question("Capital of France?", ["Paris", "Rome", "Berlin", "Madrid"], [0]),
            make_question("Capital of Japan?", ["Tokyo", "Seoul", "Osaka", "Kyoto"], [0]),
            make_question("Capital of Egypt?", ["Cairo", "Nairobi", "Accra", "Lagos"], [0]),
            make_question("Capital of Canada?", ["Ottawa", "Toronto", "Montreal", "Vancouver"], [0]),
            make_question("Capital of Brazil?", ["Brasilia", "Rio", "Sao Paulo", "Salvador"], [0]),
        ],
    }
    response = admin_client.post("/api/admin/quizzes", json=payload)
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def running_session(admin_client: TestClient, capitals_quiz: dict) -> dict:
    response = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": capitals_quiz["id"]}
    )
    assert response.status_code == 201
    return response.json()


@pytest.fixture
def student(app: FastAPI) -> Callable[[], TestClient]:
    """Factory for a fresh browser: its own cookie jar, no admin login."""

    def _student() -> TestClient:
        return TestClient(app)

    return _student
