import ipaddress
from urllib.parse import urlsplit

from fastapi.testclient import TestClient

from tests.helpers import create_quiz, make_question, quiz_payload, start_session


def session_endpoints_require_authentication(client: TestClient) -> None:
    requests: list[tuple[str, str, dict | None]] = [
        ("POST", "/api/admin/sessions", {"quiz_id": 1}),
        ("POST", "/api/admin/sessions/stop", None),
        ("GET", "/api/admin/sessions/current", None),
    ]
    for method, path, body in requests:
        response = client.request(method, path, json=body)
        assert response.status_code == 401, f"{method} {path}"


def test_session_endpoints_require_authentication(client: TestClient) -> None:
    session_endpoints_require_authentication(client)
    client.cookies.set("lanq_session", "not-a-real-token")
    session_endpoints_require_authentication(client)


def test_starting_a_session_snapshots_the_quiz(admin_client: TestClient) -> None:
    quiz = create_quiz(admin_client)

    body = start_session(admin_client, quiz["id"])

    assert isinstance(body["id"], int)
    assert body["quiz_id"] == quiz["id"]
    assert body["status"] == "active"
    assert body["title"] == "Capitals"
    assert body["time_limit_seconds"] == 600
    assert body["question_count"] == 5
    assert isinstance(body["started_at"], str)
    assert body["ended_at"] is None

    current = admin_client.get("/api/admin/sessions/current")
    assert current.status_code == 200
    assert current.json()["session"] == body


def test_status_reports_no_session_while_nothing_is_running(
    admin_client: TestClient,
) -> None:
    body = admin_client.get("/api/admin/sessions/current").json()
    assert body["session"] is None
    assert isinstance(body["join_url"], str)
    assert body["qr_svg"].lstrip().startswith("<svg")


def test_starting_a_second_session_is_refused_with_a_conflict(
    admin_client: TestClient,
) -> None:
    first = create_quiz(admin_client, "First")
    second = create_quiz(admin_client, "Second")
    start_session(admin_client, first["id"])

    response = admin_client.post(
        "/api/admin/sessions", json={"quiz_id": second["id"]}
    )
    assert response.status_code == 409
    assert "already active" in response.json()["detail"].lower()
    assert (
        admin_client.get("/api/admin/sessions/current").json()["session"][
            "quiz_id"
        ]
        == first["id"]
    )


def test_starting_a_session_for_an_unknown_quiz_returns_404(
    admin_client: TestClient,
) -> None:
    response = admin_client.post("/api/admin/sessions", json={"quiz_id": 9999})
    assert response.status_code == 404


def test_a_quiz_is_locked_while_its_session_is_active(
    admin_client: TestClient,
) -> None:
    quiz = create_quiz(admin_client)
    start_session(admin_client, quiz["id"])

    edited = admin_client.put(
        f"/api/admin/quizzes/{quiz['id']}",
        json={
            "title": "Changed mid-flight",
            "time_limit_seconds": None,
            "questions": [make_question("Q1", ["a", "b"], [0])],
        },
    )
    assert edited.status_code == 409
    assert "locked" in edited.json()["detail"].lower()

    deleted = admin_client.delete(f"/api/admin/quizzes/{quiz['id']}")
    assert deleted.status_code == 409
    assert "locked" in deleted.json()["detail"].lower()

    unchanged = admin_client.get(f"/api/admin/quizzes/{quiz['id']}")
    assert unchanged.status_code == 200
    assert unchanged.json() == quiz


def test_quizzes_other_than_the_running_one_stay_editable(
    admin_client: TestClient,
) -> None:
    running = create_quiz(admin_client, "Running")
    other = create_quiz(admin_client, "Other")
    start_session(admin_client, running["id"])

    edited = admin_client.put(
        f"/api/admin/quizzes/{other['id']}",
        json={**quiz_payload("Other"), "title": "Other edited"},
    )
    assert edited.status_code == 200
    assert edited.json()["title"] == "Other edited"


def test_a_quiz_can_be_deleted_after_its_session_has_ended(
    admin_client: TestClient,
) -> None:
    quiz = create_quiz(admin_client)
    start_session(admin_client, quiz["id"])
    assert admin_client.post("/api/admin/sessions/stop").status_code == 200

    response = admin_client.delete(f"/api/admin/quizzes/{quiz['id']}")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert admin_client.get("/api/admin/quizzes").json() == []


def test_stopping_the_session_ends_it_and_unlocks_the_quiz(
    admin_client: TestClient,
) -> None:
    quiz = create_quiz(admin_client)
    started = start_session(admin_client, quiz["id"])

    stopped = admin_client.post("/api/admin/sessions/stop")
    assert stopped.status_code == 200
    body = stopped.json()
    assert body["id"] == started["id"]
    assert body["status"] == "ended"
    assert isinstance(body["ended_at"], str)

    current = admin_client.get("/api/admin/sessions/current").json()
    assert current["session"] is None

    edited = admin_client.put(
        f"/api/admin/quizzes/{quiz['id']}",
        json={**quiz_payload(), "title": "After the session"},
    )
    assert edited.status_code == 200

    again = admin_client.post("/api/admin/sessions/stop")
    assert again.status_code == 409


def test_join_url_honours_the_environment_overrides(
    admin_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("LANQ_LAN_IP", "10.20.30.40")
    monkeypatch.setenv("LANQ_PORT", "9001")

    body = admin_client.get("/api/admin/sessions/current").json()
    assert body["join_url"] == "http://10.20.30.40:9001/"


def test_join_url_defaults_to_port_8000(
    admin_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("LANQ_LAN_IP", "10.20.30.40")
    monkeypatch.delenv("LANQ_PORT", raising=False)

    body = admin_client.get("/api/admin/sessions/current").json()
    assert body["join_url"] == "http://10.20.30.40:8000/"


def test_join_url_falls_back_to_a_detected_lan_address(
    admin_client: TestClient, monkeypatch
) -> None:
    monkeypatch.delenv("LANQ_LAN_IP", raising=False)
    monkeypatch.delenv("LANQ_PORT", raising=False)

    body = admin_client.get("/api/admin/sessions/current").json()
    parts = urlsplit(body["join_url"])
    assert parts.scheme == "http"
    assert parts.path == "/"
    assert parts.port == 8000
    assert parts.hostname is not None
    ipaddress.ip_address(parts.hostname)


def test_the_qr_code_is_an_svg_that_follows_the_join_url(
    admin_client: TestClient, monkeypatch
) -> None:
    monkeypatch.setenv("LANQ_LAN_IP", "10.20.30.40")
    monkeypatch.setenv("LANQ_PORT", "9001")
    first = admin_client.get("/api/admin/sessions/current").json()
    assert first["qr_svg"].lstrip().startswith("<svg")
    assert "<path" in first["qr_svg"]

    monkeypatch.setenv("LANQ_LAN_IP", "10.20.30.41")
    second = admin_client.get("/api/admin/sessions/current").json()
    assert second["join_url"] != first["join_url"]
    assert second["qr_svg"] != first["qr_svg"]
