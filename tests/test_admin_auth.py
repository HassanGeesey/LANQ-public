from collections.abc import Callable

from fastapi.testclient import TestClient

USERNAME = "ms.Rivera"
PASSWORD = "correct horse"


def test_login_issues_opaque_token_cookie(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()

    response = client.post(
        "/api/admin/login", json={"username": USERNAME, "password": PASSWORD}
    )
    assert response.status_code == 200
    assert response.json() == {"username": USERNAME}
    token = response.cookies.get("lanq_session")
    assert token
    assert len(token) >= 32

    me = client.get("/api/admin/me")
    assert me.status_code == 200
    assert me.json() == {"username": USERNAME}


def test_wrong_username_and_wrong_password_share_one_generic_error(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()

    bad_username = client.post(
        "/api/admin/login", json={"username": "nobody", "password": PASSWORD}
    )
    bad_password = client.post(
        "/api/admin/login", json={"username": USERNAME, "password": "wrong"}
    )

    assert bad_username.status_code == 401
    assert bad_password.status_code == 401
    assert bad_username.json() == bad_password.json()
    detail = str(bad_username.json()["detail"]).lower()
    assert USERNAME.lower() not in detail
    assert "password" not in detail or "invalid" in detail
    assert client.get("/api/admin/me").status_code == 401


def test_admin_endpoints_reject_missing_and_invalid_tokens(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()

    assert client.get("/api/admin/me").status_code == 401
    assert client.post("/api/admin/logout").status_code == 401
    assert (
        client.post(
            "/api/admin/change-password",
            json={"current_password": PASSWORD, "new_password": "new"},
        ).status_code
        == 401
    )

    client.cookies.set("lanq_session", "not-a-real-token")
    assert client.get("/api/admin/me").status_code == 401


def test_logout_invalidates_all_tokens_permanently(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()
    client.post("/api/admin/login", json={"username": USERNAME, "password": PASSWORD})
    first_token = client.cookies.get("lanq_session")
    client.post("/api/admin/login", json={"username": USERNAME, "password": PASSWORD})
    second_token = client.cookies.get("lanq_session")
    assert first_token != second_token

    response = client.post("/api/admin/logout")
    assert response.status_code == 200

    for stale in (first_token, second_token):
        client.cookies.set("lanq_session", stale)
        assert client.get("/api/admin/me").status_code == 401


def test_change_password_requires_the_current_password(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()
    client.post("/api/admin/login", json={"username": USERNAME, "password": PASSWORD})

    response = client.post(
        "/api/admin/change-password",
        json={"current_password": "wrong", "new_password": "rotated"},
    )
    assert response.status_code == 400
    assert client.get("/api/admin/me").status_code == 200
    assert (
        client.post(
            "/api/admin/login", json={"username": USERNAME, "password": PASSWORD}
        ).status_code
        == 200
    )


def test_change_password_invalidates_all_prior_tokens(
    client: TestClient, setup_teacher: Callable[..., None]
) -> None:
    setup_teacher()
    client.post("/api/admin/login", json={"username": USERNAME, "password": PASSWORD})
    first_token = client.cookies.get("lanq_session")
    client.post("/api/admin/login", json={"username": USERNAME, "password": PASSWORD})
    second_token = client.cookies.get("lanq_session")
    assert first_token != second_token

    response = client.post(
        "/api/admin/change-password",
        json={"current_password": PASSWORD, "new_password": "rotated"},
    )
    assert response.status_code == 200

    for stale in (first_token, second_token):
        client.cookies.set("lanq_session", stale)
        assert client.get("/api/admin/me").status_code == 401

    assert (
        client.post(
            "/api/admin/login", json={"username": USERNAME, "password": PASSWORD}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/api/admin/login",
            json={"username": USERNAME, "password": "rotated"},
        ).status_code
        == 200
    )

