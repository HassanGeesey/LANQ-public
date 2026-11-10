import re

from fastapi.testclient import TestClient

EXTERNAL_URL = re.compile(r"https?://|//\w")


def served_paths(response_text: str) -> list[str]:
    return re.findall(r'(?:src|href)="([^"]+)"', response_text)


def test_admin_page_offers_setup_login_logout_and_change_password(
    client: TestClient,
) -> None:
    response = client.get("/admin")
    assert response.status_code == 200
    assert 'id="login-form"' in response.text
    assert 'id="setup-form"' in response.text
    assert 'id="logout-button"' in response.text
    assert 'id="change-password-form"' in response.text


def test_admin_page_offers_the_quiz_library_and_editor(
    client: TestClient,
) -> None:
    response = client.get("/admin")
    assert response.status_code == 200
    for element_id in (
        "quiz-list",
        "new-quiz-button",
        "quiz-editor",
        "quiz-title",
        "question-list",
        "add-question-button",
        "save-quiz-button",
        "cancel-quiz-button",
        "editor-error-summary",
    ):
        assert f'id="{element_id}"' in response.text, element_id


def test_all_pages_and_assets_are_local(client: TestClient) -> None:
    for page in ("/", "/admin"):
        page_response = client.get(page)
        assert page_response.status_code == 200
        assert not EXTERNAL_URL.search(page_response.text), page

        for asset_path in served_paths(page_response.text):
            assert asset_path.startswith("/"), asset_path
            asset = client.get(asset_path)
            assert asset.status_code == 200, asset_path
            assert not EXTERNAL_URL.search(asset.text), asset_path
