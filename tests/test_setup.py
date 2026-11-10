from fastapi.testclient import TestClient


def test_setup_state_reports_pending_before_setup(client: TestClient) -> None:
    response = client.get("/api/admin/setup-state")
    assert response.status_code == 200
    assert response.json() == {"setup_complete": False}


def test_first_run_setup_creates_the_teacher_account(client: TestClient) -> None:
    response = client.post(
        "/api/admin/setup", json={"username": "ms.Rivera", "password": "correct horse"}
    )
    assert response.status_code == 201
    assert response.json() == {"setup_complete": True}

    state = client.get("/api/admin/setup-state")
    assert state.json() == {"setup_complete": True}


def test_setup_is_refused_once_an_account_exists(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"username": "ms.Rivera", "password": "first"})

    response = client.post(
        "/api/admin/setup", json={"username": "attacker", "password": "second"}
    )
    assert response.status_code == 403
    assert client.get("/api/admin/setup-state").json() == {"setup_complete": True}
