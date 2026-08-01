from fastapi.testclient import TestClient

from core.web.app import create_app


def test_control_token_allows_configured_frontend_port(monkeypatch):
    monkeypatch.setenv("VIBELUTION_PORT", "8100")
    monkeypatch.setenv("VIBELUTION_FRONTEND_PORT", "5200")
    client = TestClient(create_app(), base_url="http://127.0.0.1:8100")

    response = client.get(
        "/api/control-token",
        headers={"Origin": "http://127.0.0.1:5200"},
    )

    assert response.status_code == 200
    assert response.json()["controlToken"]
