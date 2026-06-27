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


def test_reset_routes_report_migration_to_launcher():
    response = client.get("/api/reset/summary")

    assert response.status_code == 410
    payload = response.json()["detail"]
    assert payload["code"] == "reset_migrated_to_launcher"
    assert payload["launcherPath"] == "/launcher"
