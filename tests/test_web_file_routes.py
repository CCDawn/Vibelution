from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_files_tree_lists_repo_entries():
    response = client.get("/api/files/tree")
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert any(item["name"] == "core" for item in payload)
    assert any(item["name"] == "docs" for item in payload)


def test_file_content_rejects_path_escape():
    response = client.get("/api/files/content", params={"path": "../outside.txt"})
    assert response.status_code == 400
    assert "project root" in response.json()["detail"]
