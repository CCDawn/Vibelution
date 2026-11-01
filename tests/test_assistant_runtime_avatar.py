"""The private avatar projects only the bound native identity and safe files."""

import base64
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from core.assistant_runtime import assistant_avatar as avatar
from core.assistant_runtime import native
from core.assistant_runtime.host import create_app

PNG = b"\x89PNG\r\n\x1a\nsynthetic"
SVG = b'<svg xmlns="http://www.w3.org/2000/svg"><path /></svg>'


@pytest.fixture
def binding(tmp_path, monkeypatch):
    config = tmp_path / "config" / "config.toml"
    config.parent.mkdir()
    config.write_text('secret = "DO_NOT_EXPOSE"', encoding="utf-8")
    root = tmp_path / "native-profile"
    source_root = tmp_path / "shipped-code"
    bundled = source_root / "assets" / avatar.directory.AGENT_AVATAR_ASSET_DIR_NAME
    bundled.mkdir(parents=True)
    custom = config.parent / avatar.directory.AGENT_AVATAR_CONFIG_DIR_NAME / avatar.directory.AGENT_AVATAR_CONFIG_AGENT_DIR_NAME
    custom.mkdir(parents=True)
    legacy = tmp_path / "legacy"
    monkeypatch.setattr(avatar.public_config, "resolve_config_path", lambda: config)
    monkeypatch.setattr(avatar.directory, "CONFIG_PATH", config)
    monkeypatch.setattr(avatar.directory, "_active_project_root", lambda: avatar.directory._SCOPED_PROJECT_ROOT.get() or root)
    monkeypatch.setattr(avatar, "_bundled_root", lambda: source_root)
    monkeypatch.setattr(avatar.directory, "_workspace_path", lambda *a, **kw: legacy)
    agent = {"agentId": "bound", "directSessionId": "session", "metadata": {},
             "llmBindings": {"dialogue": {"modelId": "openai/gpt-4o"}}}
    monkeypatch.setattr(native, "_STARTED", True)
    monkeypatch.setattr(native, "_AGENT_ID", "bound")
    monkeypatch.setattr(native, "_SESSION_ID", "session")
    monkeypatch.setattr(native, "_projection", lambda: {"assistant": {"agentId": "bound", "directSessionId": "session"}})
    monkeypatch.setattr(native, "_services", lambda: (SimpleNamespace(get_agent_parameter_snapshot=lambda *a, **k: dict(agent)), None, None, None))
    return config, bundled, custom, agent


def test_model_svg_and_custom_raster_revision_follow_selection_and_content(binding):
    config, bundled, custom, agent = binding
    (bundled / "model-openai.svg").write_bytes(SVG)
    first = native.read_assistant_avatar()
    assert first["agentId"] == "bound" and first["schemaVersion"] == 1
    assert first["image"]["contentType"] == "image/svg+xml"
    assert base64.b64decode(first["image"]["dataBase64"]) == SVG
    revision = native.assistant_avatar_revision()
    assert len(revision) == 64
    (custom / "mine.png").write_bytes(PNG)
    agent["metadata"] = {"avatarImagePath": "workspace/avatars/mine.png", "avatarImageSource": "user"}
    second = native.assistant_avatar_revision()
    assert second != revision
    assert base64.b64decode(native.read_assistant_avatar()["image"]["dataBase64"]) == PNG
    (custom / "mine.png").write_bytes(PNG + b"changed")
    third = native.assistant_avatar_revision()
    assert third not in {revision, second}
    config.write_text('secret = "changed"', encoding="utf-8")
    assert native.assistant_avatar_revision() != third


@pytest.mark.parametrize(("filename", "payload", "content_type"), [
    ("mine.jpg", b"\xff\xd8\xffsynthetic", "image/jpeg"),
    ("mine.webp", b"RIFF\x10\x00\x00\x00WEBPsynthetic", "image/webp"),
])
def test_custom_raster_formats(binding, filename, payload, content_type):
    _, _, custom, agent = binding
    (custom / filename).write_bytes(payload)
    agent["metadata"] = {"avatarImagePath": "workspace/avatars/" + filename, "avatarImageSource": "user"}
    image = native.read_assistant_avatar()["image"]
    assert image["contentType"] == content_type
    assert base64.b64decode(image["dataBase64"]) == payload


def test_custom_model_svg_cannot_shadow_bundled_asset(binding):
    _, bundled, custom, agent = binding
    (bundled / "model-openai.svg").write_bytes(SVG)
    (custom / "model-openai.svg").write_bytes(b"<svg>UNTRUSTED</svg>")
    agent["metadata"] = {"avatarImagePath": "workspace/avatars/model-openai.svg", "avatarImageSource": "user"}
    assert base64.b64decode(native.read_assistant_avatar()["image"]["dataBase64"]) == SVG


def test_empty_avatar_is_a_valid_projection(binding):
    assert native.read_assistant_avatar() == {"schemaVersion": 1, "agentId": "bound", "image": None}
    assert len(native.assistant_avatar_revision()) == 64


def test_invalid_image_is_bounded_on_read(binding):
    _, _, custom, agent = binding
    (custom / "invalid.png").write_bytes(b"not an image")
    agent["metadata"] = {"avatarImagePath": "workspace/avatars/invalid.png", "avatarImageSource": "user"}
    with pytest.raises(ValueError, match="^assistant_avatar_unavailable$"):
        native.read_assistant_avatar()


def test_linked_custom_file_is_rejected(binding, tmp_path):
    _, _, custom, agent = binding
    outside = tmp_path / "outside.png"
    outside.write_bytes(PNG)
    try:
        (custom / "link.png").symlink_to(outside)
    except OSError:
        pytest.skip("symlinks unavailable")
    agent["metadata"] = {"avatarImagePath": "workspace/avatars/link.png", "avatarImageSource": "user"}
    assert native.assistant_avatar_revision() is None
    with pytest.raises(ValueError, match="^assistant_avatar_unavailable$"):
        native.read_assistant_avatar()


@pytest.mark.parametrize("selection", ["../../secret.png", "https://invalid/a.png", "workspace/avatars/evil.svg"])
def test_unsafe_selection_is_not_replaced_with_default(binding, selection):
    _, _, _, agent = binding
    agent["metadata"] = {"avatarImagePath": selection, "avatarImageSource": "user"}
    assert native.assistant_avatar_revision() is None
    with pytest.raises(ValueError, match="^assistant_avatar_unavailable$"):
        native.read_assistant_avatar()


def test_wrong_identity_and_missing_config_are_refused_without_initialization(binding, monkeypatch, tmp_path):
    _, _, _, agent = binding
    agent["agentId"] = "other"
    with pytest.raises(ValueError, match="^assistant_avatar_unavailable$"):
        native.read_assistant_avatar()
    missing = tmp_path / "absent" / "config.toml"
    monkeypatch.setattr(avatar.public_config, "resolve_config_path", lambda: missing)
    monkeypatch.setattr(native, "_projection", lambda: pytest.fail("must not initialize native owner"))
    assert native.assistant_avatar_revision() is None
    with pytest.raises(ValueError, match="^assistant_avatar_unavailable$"):
        native.read_assistant_avatar()
    assert not missing.parent.exists()


def test_private_endpoint_rejects_parameters_and_bounds_errors():
    class Owner:
        def bootstrap(self): return {"assistant": {"agentId": "bound", "directSessionId": "session"}}
        def shutdown(self): pass
        def avatar(self): raise ValueError("SECRET-PATH")
    with TestClient(create_app(native=Owner(), token="private-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-test-token"}) as client:
        assert client.get("/api/assistant/avatar?agentId=other").status_code == 422
        assert client.request("GET", "/api/assistant/avatar", content=b"{}").status_code == 422
        response = client.get("/api/assistant/avatar")
        assert response.status_code == 503
        assert response.json() == {"detail": {"code": "assistant_avatar_unavailable"}}
