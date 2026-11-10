from fastapi.testclient import TestClient


def test_student_page_loads_at_root(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "no active quiz" in response.text.lower()


def test_student_state_is_no_quiz_when_nothing_is_running(client: TestClient) -> None:
    response = client.get("/api/student/state")
    assert response.status_code == 200
    assert response.json() == {"state": "no_quiz"}
