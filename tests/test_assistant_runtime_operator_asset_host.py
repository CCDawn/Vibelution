"""Selected operator images stay on the private UI transport, never model actions."""
from fastapi.testclient import TestClient

from core.assistant_runtime.host import create_app


class Native:
    def bootstrap(self):
        return {"assistant": {"agentId": "synthetic", "directSessionId": "synthetic"}}

    def shutdown(self):
        pass


def test_operator_assets_have_fixed_kinds_and_reuse_the_existing_private_boundary(monkeypatch):
    from core.assistant_runtime import operator_assets
    calls = []
    def read(kind):
        calls.append(kind)
        return {"schemaVersion": 1, "kind": kind, "image": None, "readability": "standard"}
    monkeypatch.setattr(operator_assets, "read_operator_asset", read)
    headers = {"Authorization": "Bearer private-asset-test-token"}
    with TestClient(create_app(native=Native(), token="private-asset-test-token"), base_url="http://127.0.0.1") as client:
        path = "/api/assistant/operator-assets/avatar"
        assert client.get(path).status_code == 401
        assert client.get(path, headers={**headers, "Origin": "https://untrusted.invalid"}).status_code == 403
        assert client.get(path, headers=headers).json() == read("avatar")
        calls.clear()
        for suffix in ("file", "..%2Fprivate", "background?path=private", "avatar?url=https://untrusted.invalid"):
            assert client.get("/api/assistant/operator-assets/" + suffix, headers=headers).status_code in {404, 422}
        assert calls == []


def test_asset_failure_does_not_return_paths_credentials_or_internal_errors(monkeypatch):
    from core.assistant_runtime import operator_assets
    def fail(_kind):
        raise ValueError("SECRET /private/operator/config.toml")
    monkeypatch.setattr(operator_assets, "read_operator_asset", fail)
    with TestClient(create_app(native=Native(), token="private-asset-test-token"), base_url="http://127.0.0.1",
                    headers={"Authorization": "Bearer private-asset-test-token"}) as client:
        result = client.get("/api/assistant/operator-assets/background")
        assert result.status_code == 503
        assert "SECRET" not in result.text and "/private" not in result.text
        assert "operator_asset_unavailable" in result.text


def test_status_exposes_only_opaque_asset_revisions(monkeypatch):
    from core.assistant_runtime import host, native, operator_assets
    from tools import pa_assistant_actions
    monkeypatch.setattr(native, "identity", lambda: {"assistant": {"agentId": "fixture", "directSessionId": "fixture"}})
    monkeypatch.setattr(pa_assistant_actions, "execute", lambda *args, **kwargs: {})
    monkeypatch.setattr(host, "_operator_profile", lambda: None)
    monkeypatch.setattr(operator_assets, "operator_asset_revisions", lambda: {"avatar": "a" * 64, "background": None})
    result = host.NativeFacade(None).identity()
    assert result["operatorAssetRevisions"] == {"avatar": "a" * 64, "background": None}
    assert result["operatorAssetsVersion"] == 1
