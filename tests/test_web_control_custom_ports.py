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


def test_avatar_and_theme_image_gets_are_tokenless_but_still_local_only(monkeypatch, tmp_path):
    from core.web.routes import agents as agent_routes

    avatar_file = tmp_path / "avatar.png"
    avatar_file.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    monkeypatch.setattr(agent_routes, "resolve_agent_avatar_file", lambda _filename: avatar_file)
    client = TestClient(create_app())

    agent_avatar = client.get("/api/agents/avatar-image/01-session-agent.png")
    assert agent_avatar.status_code == 200
    assert agent_avatar.headers["content-type"].startswith("image/png")

    # Missing files must reach their route and report 404, rather than failing
    # at the API control-token middleware before a native image element can load.
    assert client.get("/api/config/avatar-image/missing.png").status_code == 404
    assert client.get("/api/config/theme-background-image/missing.png").status_code == 404

    remote_client = TestClient(create_app(), base_url="http://192.168.20.30:8000")
    assert remote_client.get("/api/agents/avatar-image/01-session-agent.png").status_code == 403
