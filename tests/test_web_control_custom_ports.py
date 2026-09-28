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


def test_session_image_artifact_gets_are_tokenless_but_documents_and_mutations_stay_gated(
    monkeypatch, tmp_path
):
    """Session image artifacts must load like avatar/theme images (no token).

    Browser-native `<img>` loads and `?download=1` navigation cannot attach the
    X-Vibelution-Control-Token header, so image-extension artifact ids are
    exempt on GET only. The narrow gate keeps everything else behind the token:
    document artifacts (text/PDF extensions), multi-segment artifact paths, and
    mutating methods. The trusted-source (host) check still applies to exempt
    GETs, mirroring the avatar/theme precedent (47e6149a5).
    """
    from core.web.routes import sessions as session_routes

    image_file = tmp_path / "user-image-1730000000000-deadbeef.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    monkeypatch.setattr(
        session_routes,
        "resolve_session_image_artifact",
        lambda _session_id, _artifact_id: (image_file, "image/png"),
    )
    client = TestClient(create_app())
    image_url = "/api/sessions/e2e-session/artifacts/user-image-1730000000000-deadbeef.png"

    served = client.get(image_url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")

    # The download link is the same path plus a query string; native <a>
    # navigation must reach the file without a token too.
    download = client.get(f"{image_url}?download=1")
    assert download.status_code == 200

    # Document artifacts and traversal-shaped/multi-segment artifact paths fail
    # closed at the middleware (403 token error), never reaching the route.
    token_error = "Missing or invalid web control token"
    document = client.get(
        "/api/sessions/e2e-session/artifacts/user-doc-1730000000000-deadbeef.md"
    )
    assert document.status_code == 403
    assert document.json()["detail"] == token_error
    nested = client.get(f"{image_url.rsplit('/', 1)[0]}/nested/user-image-1.png")
    assert nested.status_code == 403
    assert nested.json()["detail"] == token_error

    # Mutating methods on an exempt image-artifact path are never tokenless.
    assert client.post(image_url).status_code == 403
    assert client.delete(image_url).status_code == 403

    # The trusted-source check is preserved for exempt GETs.
    remote_client = TestClient(create_app(), base_url="http://192.168.20.30:8000")
    assert remote_client.get(image_url).status_code == 403


def test_session_artifact_image_exemption_extensions_match_route_whitelist():
    """The middleware's image-extension set must equal the route's whitelist.

    resolve_session_image_artifact (core/web/services/session/image_attachments.py)
    only serves extensions from _SESSION_IMAGE_ARTIFACT_CONTENT_TYPES; the
    source-only GET gate must never exempt an artifact id the route would not
    serve as an image.
    """
    from core.web import control
    from core.web.services import session_service

    expected = {
        f".{extension}"
        for extension in session_service._SESSION_IMAGE_ARTIFACT_CONTENT_TYPES
    }
    assert set(control._SESSION_ARTIFACT_IMAGE_EXTENSIONS) == expected
