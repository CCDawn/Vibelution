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
    _write_note(source, "Guide.md", "# Guide\nAgent reference content\n[[Other]]\n- [ ] check route\n#route")
    _write_note(source, "Other.md", "# Other\n")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})
    user_id = "route-user"

    preview = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(source), "userId": user_id})
    assert preview.status_code == 200
    assert preview.json()["summary"]["markdownFileCount"] == 2

    imported = client.post(
        "/api/user-content/markdown-spaces/import",
        json={"sourcePath": str(source), "spaceName": "Docs", "userId": user_id},
    )
    assert imported.status_code == 201
    space_id = imported.json()["space"]["spaceId"]

    listed = client.get("/api/user-content/markdown-spaces", params={"userId": user_id})
    assert listed.status_code == 200
    listed_payload = listed.json()
    assert listed_payload["summary"]["spaceCount"] == 1
    listed_space = listed_payload["spaces"][0]
    assert listed_space["userId"] == user_id
    assert listed_space["sourceRef"]["path"] == str(source.resolve())
    assert listed_space["sourceRef"]["sha256"].startswith("sha256:")
    assert listed_space["counts"] == {
        "markdownFileCount": 2,
        "pageCount": 2,
        "linkCount": 1,
        "taskCount": 1,
        "tagCount": 1,
    }

    pages = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages", params={"userId": user_id})
    assert pages.status_code == 200
    pages_payload = pages.json()
    assert pages_payload["space"]["sourceRef"] == listed_space["sourceRef"]
    assert pages_payload["space"]["counts"] == listed_space["counts"]
    page_id = pages_payload["pages"][0]["pageId"]

    page = client.get(f"/api/user-content/markdown-spaces/{space_id}/pages/{page_id}", params={"userId": user_id})
    assert page.status_code == 200
    page_payload = page.json()
    assert page_payload["space"]["sourceRef"] == listed_space["sourceRef"]
    assert page_payload["space"]["counts"] == listed_space["counts"]
    assert page_payload["content"].startswith("# Guide") or page_payload["content"].startswith("# Other")

    search = client.get("/api/user-content/markdown-spaces/search", params={"query": "reference", "userId": user_id})
    assert search.status_code == 200
    search_payload = search.json()
    assert search_payload["results"][0]["resultType"] == "user_markdown_page"
    assert search_payload["spaces"][0]["sourceRef"] == listed_space["sourceRef"]
    assert search_payload["spaces"][0]["counts"] == listed_space["counts"]


def test_user_content_route_maps_service_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(service, "PROJECT_ROOT", tmp_path / "project")
    client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})

    response = client.post("/api/user-content/markdown-spaces/import-preview", json={"sourcePath": str(tmp_path / "missing")})

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "source_path_missing"
