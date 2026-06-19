from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import file_service


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def _clear_file_tree_cache():
    with file_service._TREE_CACHE_LOCK:
        file_service._TREE_CACHE["expires_at"] = 0.0
        file_service._TREE_CACHE["nodes"] = None
        file_service._TREE_CACHE["stats"] = None


def test_files_tree_lists_repo_entries():
    response = client.get("/api/files/tree")
    assert response.status_code == 200, response.json()
    payload = response.json()
    assert any(item["name"] == "core" for item in payload)
    assert any(item["name"] == "docs" for item in payload)


def test_files_tree_skips_pytest_run_directories(tmp_path, monkeypatch):
    (tmp_path / "core").mkdir()
    (tmp_path / "docs").mkdir()
    (tmp_path / ".pytest-run-live-tool-pairing").mkdir()
    monkeypatch.setattr(file_service, "PROJECT_ROOT", tmp_path)
    _clear_file_tree_cache()

    try:
        payload = file_service.build_file_tree()
    finally:
        _clear_file_tree_cache()

    names = {item["name"] for item in payload}
    assert "core" in names
    assert "docs" in names
    assert ".pytest-run-live-tool-pairing" not in names


def test_file_content_rejects_path_escape():
    response = client.get("/api/files/content", params={"path": "../outside.txt"})
    assert response.status_code == 400
    assert "project root" in response.json()["detail"]
