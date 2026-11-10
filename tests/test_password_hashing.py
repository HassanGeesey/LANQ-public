from pathlib import Path

from fastapi.testclient import TestClient

PASSWORD = "correct horse battery staple"


def test_password_is_stored_as_salted_pbkdf2_hash_not_plaintext(
    client: TestClient, db_path: Path
) -> None:
    response = client.post(
        "/api/admin/setup", json={"username": "ms.Rivera", "password": PASSWORD}
    )
    assert response.status_code == 201

    blob = db_path.read_bytes()
    assert PASSWORD.encode("utf-8") not in blob
    assert b"pbkdf2_sha256" in blob


def test_password_is_never_returned_in_responses(client: TestClient) -> None:
    client.post("/api/admin/setup", json={"username": "ms.Rivera", "password": PASSWORD})

    assert PASSWORD not in client.get("/api/admin/setup-state").text
