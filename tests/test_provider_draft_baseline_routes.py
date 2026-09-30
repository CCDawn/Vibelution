from __future__ import annotations

import copy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from config.public_config import public_config_hash
from core.web.routes.config import router as config_router
from core.web.services import config_service, provider_config_service


@pytest.mark.parametrize(
    ("method", "path", "service_name", "extra"),
    [
        (
            "post",
            "/api/config/draft/providers/id-suggestion",
            "suggest_draft_provider_id",
            {},
        ),
        ("post", "/api/config/draft/providers", "draft_add_provider", {"providerId": "relay_a"}),
        (
            "put",
            "/api/config/draft/providers/relay_a",
            "draft_update_provider",
            {"providerId": "relay_a"},
        ),
        (
            "delete",
            "/api/config/draft/providers/relay_a",
            "draft_delete_provider",
            {"providerId": "relay_a"},
        ),
        (
            "post",
            "/api/config/draft/providers/relay_a/route-preview",
            "preview_draft_provider_route",
            {"providerId": "relay_a"},
        ),
        (
            "post",
            "/api/config/draft/providers/relay_a/discover",
            "discover_draft_provider",
            {"providerId": "relay_a"},
        ),
        (
            "post",
            "/api/config/draft/providers/relay_a/models",
            "draft_pin_provider_model",
            {"providerId": "relay_a", "upstreamId": "model-a"},
        ),
        (
            "delete",
            "/api/config/draft/providers/relay_a/models/model-a",
            "draft_unpin_provider_model",
            {"providerId": "relay_a", "upstreamId": "model-a"},
        ),
    ],
)
def test_provider_draft_routes_forward_base_config(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
    service_name: str,
    extra: dict[str, str],
) -> None:
    captured: dict[str, object] = {}

    def fake_service(*_args, **kwargs):
        captured["base_config"] = kwargs.get("base_config")
        if service_name == "preview_draft_provider_route":
            return {"providerId": "relay_a"}
        if service_name == "suggest_draft_provider_id":
            return {"suggestedProviderId": "relay_a"}
        return {}

    monkeypatch.setattr(provider_config_service, service_name, fake_service)
    app = FastAPI()
    app.include_router(config_router, prefix="/api")
    client = TestClient(app)
    baseline = {"sentinel": "the-client-edit-baseline"}
    payload = {
        "publicConfig": {},
        "baseConfig": baseline,
        "baseHash": "paired-hash",
        "draftMeta": {},
        "provider": {},
        **extra,
    }

    response = client.request(method.upper(), path, json=payload)

    assert response.status_code == 200, response.text
    assert captured["base_config"] == baseline


def _provider_config() -> dict:
    return {
        "language": "zh",
        "llm": {
            "schema_version": 2,
            "providers": {
                "relay_a": {
                    "label": "Relay A",
                    "service_class": "relay",
                    "vendor": "multi_model",
                    "driver": "openai",
                    "base_url": "https://relay.example/v1",
                    "auth_kind": "none",
                    "credential_ref": "none",
                    "requires_credential": False,
                    "protocols": {"default": "responses", "allowed": ["responses"]},
                    "discovery": {
                        "mode": "auto",
                        "adapter": "openai_compatible",
                        "cache_ttl_seconds": 3600,
                    },
                    "models": {
                        "base-model": {
                            "upstream_id": "base-model",
                            "label": "Base Model",
                            "enabled": True,
                        }
                    },
                }
            },
            "profiles": {
                "primary": {"model_ref": "relay_a/base-model", "overrides": {}}
            },
            "model_aliases": {},
        },
    }


@pytest.mark.parametrize(
    ("external_change", "expected_status"),
    [("unrelated", 200), ("target_provider", 409)],
)
def test_provider_pin_http_route_allows_unrelated_change_and_reports_target_conflict(
    monkeypatch: pytest.MonkeyPatch,
    external_change: str,
    expected_status: int,
) -> None:
    base = config_service._with_config_workspace_defaults(_provider_config())
    latest = copy.deepcopy(base)
    if external_change == "unrelated":
        latest["language"] = "en"
    else:
        latest["llm"]["providers"]["relay_a"]["base_url"] = "https://changed.example/v1"
    monkeypatch.setattr(provider_config_service, "load_public_config", lambda: copy.deepcopy(latest))
    monkeypatch.setattr(provider_config_service, "_record_provider_event", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        provider_config_service,
        "_build_workspace",
        lambda public_config, *, base_hash, **_kwargs: {
            "publicConfig": copy.deepcopy(public_config),
            "baseHash": base_hash,
            "hash": "draft-hash",
        },
    )
    app = FastAPI()
    app.include_router(config_router, prefix="/api")
    client = TestClient(app)
    base_hash = public_config_hash(base)

    response = client.post(
        "/api/config/draft/providers/relay_a/models",
        json={
            "publicConfig": base,
            "baseConfig": base,
            "baseHash": base_hash,
            "draftMeta": {},
            "providerId": "relay_a",
            "upstreamId": "new-model",
            "modelKey": "new-model",
            "label": "New Model",
        },
    )

    assert response.status_code == expected_status, response.text
    if expected_status == 200:
        assert "new-model" in response.json()["publicConfig"]["llm"]["providers"]["relay_a"]["models"]
    else:
        assert "当前供应商" in response.json()["detail"]
