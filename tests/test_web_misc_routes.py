import pytest
from fastapi.testclient import TestClient

from core.web.app import create_app
from core.web.control import CONTROL_TOKEN_HEADER, get_control_token

pytestmark = pytest.mark.serial


client = TestClient(create_app(), headers={CONTROL_TOKEN_HEADER: get_control_token()})


def test_pet_summary_shape():
    response = client.get("/api/pet/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"]
    assert "statusLine" in payload


def test_web_search_health_endpoint_reports_token_dependency(monkeypatch):
    from tools import web_search_tool

    monkeypatch.setattr(
        web_search_tool,
        "check_autoglm_token_service",
        lambda: {
            "available": False,
            "dependency": "autoglm_token_service",
            "stage": "token_fetch",
            "status": "unavailable",
            "tokenUrl": "http://127.0.0.1:53699/get_token",
            "searchApiCalled": False,
        },
    )

    response = client.get("/api/tools/web-search/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["toolId"] == "web_search_tool"
    assert payload["available"] is False
    assert payload["dependency"] == "autoglm_token_service"
    assert payload["stage"] == "token_fetch"
    assert payload["searchApiCalled"] is False


def test_reset_summary_shape():
    response = client.get("/api/reset/summary")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "custom"
    assert payload["presets"] == []
    assert payload["items"]
    assert payload["categories"]
    item_ids = {item["id"] for item in payload["items"]}
    assert "chat_history" in item_ids
    assert "web_dist" in item_ids
    protected_paths = {path for group in payload["protected"] for path in group["paths"]}
    assert "workspace/agent_brain.db" not in protected_paths
    assert "workspace/memory/" not in protected_paths
    assert "workspace/prompts/" not in protected_paths
    assert "workspace/prompts/DYNAMIC.md" in protected_paths
    assert ".docs/project-memory/" in protected_paths
