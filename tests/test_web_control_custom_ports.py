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


def test_session_artifact_gets_are_tokenless_but_unknown_extensions_and_mutations_stay_gated(
    monkeypatch, tmp_path
):
    """Session image/document artifacts must load like avatar/theme images.

    Browser-native `<img>` loads and `?download=1` navigation cannot attach the
    X-Vibelution-Control-Token header, so image- and document-extension
    artifact ids are exempt on GET only (documents follow the image precedent
    from 2ff8ab4bd: timeline file cards navigate with a plain href). The
    narrow gate keeps everything else behind the token: artifact ids with
    extensions outside both allowlists (.docx etc.), multi-segment artifact
    paths, and mutating methods. The trusted-source (host) check still applies
    to exempt GETs, mirroring the avatar/theme precedent (47e6149a5).
    """
    from core.web.routes import sessions as session_routes
    from core.web.services.session import document_attachments as document_module

    image_file = tmp_path / "user-image-1730000000000-deadbeef.png"
    image_file.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    document_file = tmp_path / "user-doc-1730000000000-deadbeef.md"
    document_file.write_text("# report\n", encoding="utf-8")

    def _fake_image_resolver(_session_id, artifact_id):
        # Mirror the real route flow: non-image extensions fall through to the
        # document resolver instead of being served as images.
        if not str(artifact_id).lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            raise FileNotFoundError(artifact_id)
        return (image_file, "image/png")

    monkeypatch.setattr(session_routes, "resolve_session_image_artifact", _fake_image_resolver)
    monkeypatch.setattr(
        document_module,
        "resolve_session_document_artifact",
        lambda _session_id, _artifact_id: (document_file, "text/plain"),
    )
    client = TestClient(create_app())
    image_url = "/api/sessions/e2e-session/artifacts/user-image-1730000000000-deadbeef.png"
    document_url = "/api/sessions/e2e-session/artifacts/user-doc-1730000000000-deadbeef.md"

    served = client.get(image_url)
    assert served.status_code == 200
    assert served.headers["content-type"].startswith("image/png")

    # The download link is the same path plus a query string; native <a>
    # navigation must reach the file without a token too.
    download = client.get(f"{image_url}?download=1")
    assert download.status_code == 200

    # Document artifacts share the same tokenless GET treatment now.
    document = client.get(document_url)
    assert document.status_code == 200
    assert document.headers["content-type"].startswith("text/plain")

    # Artifact ids outside both extension allowlists (.docx etc.) and
    # traversal-shaped/multi-segment artifact paths fail closed at the
    # middleware (403 token error), never reaching the route.
    token_error = "Missing or invalid web control token"
    unsupported = client.get(
        "/api/sessions/e2e-session/artifacts/user-doc-1730000000000-deadbeef.docx"
    )
    assert unsupported.status_code == 403
    assert unsupported.json()["detail"] == token_error
    nested_image = client.get(f"{image_url.rsplit('/', 1)[0]}/nested/user-image-1.png")
    assert nested_image.status_code == 403
    assert nested_image.json()["detail"] == token_error
    nested_document = client.get(f"{document_url.rsplit('/', 1)[0]}/nested/report.md")
    assert nested_document.status_code == 403
    assert nested_document.json()["detail"] == token_error

    # Mutating methods on an exempt artifact path are never tokenless.
    assert client.post(image_url).status_code == 403
    assert client.delete(image_url).status_code == 403
    assert client.post(document_url).status_code == 403
    assert client.delete(document_url).status_code == 403

    # The trusted-source check is preserved for exempt GETs.
    remote_client = TestClient(create_app(), base_url="http://192.168.20.30:8000")
    assert remote_client.get(image_url).status_code == 403
    assert remote_client.get(document_url).status_code == 403


def test_session_document_artifact_gets_are_tokenless_for_inline_and_download(
    monkeypatch, tmp_path
):
    """Document artifacts must serve without a token, inline and as download.

    Timeline file cards for text/PDF attachments navigate with a plain href
    (`url` inline, `?download=1` for downloadUrl), so document-extension
    artifact ids need the same source-only GET gate as images. A missing
    document artifact must reach the route and report 404 rather than failing
    at the middleware with a 403 token error.
    """
    from core.web.routes import sessions as session_routes
    from core.web.services.session import document_attachments as document_module

    def _failing_image_resolver(_session_id, artifact_id):
        raise FileNotFoundError(artifact_id)

    md_file = tmp_path / "user-doc-1730000000000-cafebabe.md"
    md_file.write_text("# meeting notes\n", encoding="utf-8")
    pdf_file = tmp_path / "user-doc-1730000000100-cafebabe.pdf"
    pdf_file.write_bytes(b"%PDF-1.4\n%fake-pdf-bytes\n")

    def _fake_document_resolver(_session_id, artifact_id):
        if artifact_id == md_file.name:
            return (md_file, "text/plain")
        if artifact_id == pdf_file.name:
            return (pdf_file, "application/pdf")
        raise FileNotFoundError(artifact_id)

    monkeypatch.setattr(session_routes, "resolve_session_image_artifact", _failing_image_resolver)
    monkeypatch.setattr(
        document_module, "resolve_session_document_artifact", _fake_document_resolver
    )
    client = TestClient(create_app())
    md_url = "/api/sessions/e2e-session/artifacts/user-doc-1730000000000-cafebabe.md"
    pdf_url = "/api/sessions/e2e-session/artifacts/user-doc-1730000000100-cafebabe.pdf"

    inline_md = client.get(md_url)
    assert inline_md.status_code == 200
    assert inline_md.headers["content-type"].startswith("text/plain")

    download_pdf = client.get(f"{pdf_url}?download=1")
    assert download_pdf.status_code == 200
    assert download_pdf.headers["content-type"].startswith("application/pdf")
    assert "attachment" in download_pdf.headers.get("content-disposition", "")

    # Extension-shaped exemption only: a missing document artifact id still
    # passes the gate and reaches the route, which reports 404.
    missing = client.get(
        "/api/sessions/e2e-session/artifacts/user-doc-1730000000200-cafebabe.md"
    )
    assert missing.status_code == 404


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


def test_session_artifact_document_exemption_extensions_match_service_whitelist():
    """The middleware's document-extension set must equal the service allowlist.

    resolve_session_document_artifact
    (core/web/services/session/document_attachments.py) only serves
    SESSION_DOCUMENT_ALL_EXTENSIONS; the source-only GET gate must never exempt
    an artifact id the route would not serve as a document.
    """
    from core.web import control
    from core.web.services.session import document_attachments

    expected = {
        f".{extension}"
        for extension in document_attachments.SESSION_DOCUMENT_ALL_EXTENSIONS
    }
    assert set(control._SESSION_ARTIFACT_DOCUMENT_EXTENSIONS) == expected
