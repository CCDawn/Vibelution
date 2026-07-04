from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token
from core.web.services import user_content_markdown_service as service


def _write_note(root: Path, relative: str, text: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_user_content_import_and_search_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "project")
    source = tmp_path / "source"
    _write_note(source, "Guide.md", "# Guide\nAgent reference content\n[[Other]]")
    _write_note(source, "Other.md", "# Other\n")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    preview = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(source)})
    assert preview.status_code == 200
    assert preview.json()["summary"]["markdownFileCount"] == 2

    imported = client.post(
        "/api/user-content/markdown-spaces/import",
        json={"sourcePath": str(source), "spaceName": "Docs"},
    )
    assert imported.status_code == 201
    space_id = imported.json()["space"]["spaceId"]

    listed = client.get("/api/user-content/markdown-spaces")
    assert listed.status_code == 200
    assert listed.json()["summary"]["spaceCount"] == 1

    pages = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages")
    assert pages.status_code == 200
    page_id = pages.json()["pages"][0]["pageId"]

    page = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages/{page_id}")
    assert page.status_code == 200
    assert page.json()["content"].startswith("# Guide") or page.json()["content"].startswith("# Other")

    search = client.get("/api/user-content/markdown-spaces/search", params={"query": "reference"})
    assert search.status_code == 200
    assert search.json()["results"][0]["resultType"] == "user_markdown_page"


def test_user_content_route_maps_service_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "project")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    response = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(tmp_path / "missing")})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "source_path_missing"
