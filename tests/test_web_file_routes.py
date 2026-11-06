import os
import sys

import pytest
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


def _create_directory_symlink(link, target):
    try:
        os.symlink(target, link, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable on this host: {exc}")


def _build_tree_with_cleared_cache():
    _clear_file_tree_cache()
    try:
        return file_service.build_file_tree()
    finally:
        _clear_file_tree_cache()


def _child_names(node):
    return {child["name"] for child in node.get("children", [])}


def test_files_tree_lists_repo_entries(tmp_path, monkeypatch):
    # Synthetic project root: the assertion target is the tree contract, not
    # the real checkout, whose size can exhaust the node budget and truncate
    # top-level entries depending on the environment.
    project_root = tmp_path / "project"
    (project_root / "core" / "web").mkdir(parents=True)
    (project_root / "core" / "__init__.py").write_text("", encoding="utf-8")
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.md").write_text("# notes\n", encoding="utf-8")
    (project_root / "README.md").write_text("readme\n", encoding="utf-8")
    monkeypatch.setattr(file_service, "PROJECT_ROOT", project_root)
    _clear_file_tree_cache()

    try:
        response = client.get("/api/files/tree")
    finally:
        _clear_file_tree_cache()

    assert response.status_code == 200, response.json()
    payload = response.json()
    names = {item["name"] for item in payload}
    assert "core" in names
    assert "docs" in names
    core_node = next(item for item in payload if item["name"] == "core")
    assert core_node["type"] == "directory"
    assert any(child["name"] == "web" for child in core_node.get("children", []))
    docs_node = next(item for item in payload if item["name"] == "docs")
    assert any(child["path"] == "docs/notes.md" for child in docs_node.get("children", []))


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


def test_file_content_returns_text_preview():
    response = client.get("/api/files/content", params={"path": "README.md"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["path"] == "README.md"
    assert payload["language"] == "markdown"
    assert "Vibelution" in payload["content"]
    assert payload["truncated"] is False


def test_file_content_rejects_path_escape():
    response = client.get("/api/files/content", params={"path": "../outside.txt"})
    assert response.status_code == 400
    assert "project root" in response.json()["detail"]


def test_files_tree_does_not_follow_symlink_outside_project(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    outside_dir = tmp_path / "outside-secrets"
    outside_dir.mkdir()
    (outside_dir / "secret.txt").write_text("secret\n", encoding="utf-8")
    (project_root / "core").mkdir(parents=True)
    _create_directory_symlink(project_root / "core" / "external_docs", outside_dir)
    monkeypatch.setattr(file_service, "PROJECT_ROOT", project_root)

    payload = _build_tree_with_cleared_cache()

    core_node = next(item for item in payload if item["name"] == "core")
    assert "external_docs" not in _child_names(core_node)
    assert all("secret" not in name for name in _child_names(core_node))


def test_files_tree_does_not_follow_symlink_inside_project(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    docs_dir = project_root / "docs"
    docs_dir.mkdir(parents=True)
    (docs_dir / "note.md").write_text("# note\n", encoding="utf-8")
    (project_root / "core").mkdir()
    _create_directory_symlink(project_root / "core" / "docs_alias", docs_dir)
    monkeypatch.setattr(file_service, "PROJECT_ROOT", project_root)

    payload = _build_tree_with_cleared_cache()

    core_node = next(item for item in payload if item["name"] == "core")
    assert "docs_alias" not in _child_names(core_node)


@pytest.mark.skipif(
    sys.platform != "win32" or sys.version_info < (3, 12),
    reason="Path.is_junction detection requires Windows and Python 3.12+",
)
def test_files_tree_does_not_follow_junction(tmp_path, monkeypatch):
    import _winapi

    project_root = tmp_path / "project"
    outside_dir = tmp_path / "outside-junction-target"
    outside_dir.mkdir()
    (outside_dir / "junction_secret.txt").write_text("secret\n", encoding="utf-8")
    (project_root / "core").mkdir(parents=True)
    junction = project_root / "core" / "junction_docs"
    _winapi.CreateJunction(str(outside_dir), str(junction))
    monkeypatch.setattr(file_service, "PROJECT_ROOT", project_root)

    payload = _build_tree_with_cleared_cache()

    core_node = next(item for item in payload if item["name"] == "core")
    assert "junction_docs" not in _child_names(core_node)


def test_file_content_rejects_symlink_to_outside_file(tmp_path, monkeypatch):
    project_root = tmp_path / "project"
    project_root.mkdir()
    outside_file = tmp_path / "outside-secret.txt"
    outside_file.write_text("secret\n", encoding="utf-8")
    try:
        os.symlink(outside_file, project_root / "linked_secret.txt")
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlink unavailable on this host: {exc}")
    monkeypatch.setattr(file_service, "PROJECT_ROOT", project_root)

    response = client.get("/api/files/content", params={"path": "linked_secret.txt"})

    assert response.status_code == 400
    assert "project root" in response.json()["detail"]
