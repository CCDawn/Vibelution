"""Knife 3: no silent KNOWN catalog for runtime context windows; discovery write path."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from config.public_config import apply_discovered_context_windows
from core.llm import discovery as llm_discovery


def _profile(model: str = "totally-unknown-model-xyz", provider_id: str = "p1"):
    return SimpleNamespace(
        profile_id="primary",
        provider_id=provider_id,
        model=model,
        transport="chat_completions",
        contract="tool_chat",
        streaming=True,
        tool_calling_mode="auto",
        discovery_enabled=True,
        max_output_tokens=4096,
        reasoning_state_field="",
        strict_compatibility=True,
    )


def _provider(context_window=None, provider_id: str = "p1"):
    return SimpleNamespace(
        provider_id=provider_id,
        kind="openai_compatible",
        base_url="https://example.com/v1",
        context_window=context_window,
        requires_api_key=False,
        compat_mode="openai",
    )


def _config(*, model="totally-unknown-model-xyz", provider_window=None, library_entry=None):
    profile = _profile(model=model)
    provider = _provider(context_window=provider_window)

    class _LLM:
        profiles = {"primary": profile}
        model_library = {}
        if library_entry is not None:
            model_library = {"lib-1": library_entry}

        def get_profile(self, profile_id: str):
            return profile

        def get_provider(self, provider_id: str):
            return provider

        def get_model_library_entry_for_profile(self, profile):
            if library_entry is None:
                return None, None
            return "lib-1", library_entry

    return SimpleNamespace(llm=_LLM())


def test_lookup_context_window_ignores_static_known_table():
    # gpt-4o is in SUGGESTED_CONTEXT_WINDOWS but must not become runtime authority.
    assert llm_discovery._lookup_context_window("gpt-4o", 0) == 0
    assert llm_discovery._lookup_context_window("gpt-4o", 64000) == 64000
    assert llm_discovery.suggested_context_window("gpt-4o") == 128000


def test_discover_model_unknown_without_config_is_zero(monkeypatch):
    monkeypatch.setattr(
        llm_discovery,
        "capabilities_for_adapter",
        lambda provider, profile, base: base,
    )
    monkeypatch.setattr(
        llm_discovery,
        "resolve_model_capabilities",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        llm_discovery,
        "load_model_catalog_state",
        lambda: {"schemaVersion": 2, "providers": {}, "metadata": {}},
    )

    cfg = _config(model="gpt-4o", provider_window=None)
    spec = llm_discovery.discover_model(cfg, "primary")

    assert spec.context_window == 0
    assert spec.provider_details["context_window_source"] == "missing"
    # Must not invent the known-table value for gpt-4o
    assert spec.context_window != 128000


def test_discover_model_uses_model_library_then_provider(monkeypatch):
    monkeypatch.setattr(
        llm_discovery,
        "capabilities_for_adapter",
        lambda provider, profile, base: base,
    )
    monkeypatch.setattr(
        llm_discovery,
        "resolve_model_capabilities",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        llm_discovery,
        "load_model_catalog_state",
        lambda: {"schemaVersion": 2, "providers": {}, "metadata": {}},
    )

    cfg = _config(
        model="gpt-4o",
        provider_window=90000,
        library_entry={
            "model_ref": "p1/gpt-4o",
            "provider_id": "p1",
            "upstream_id": "gpt-4o",
            "model": "gpt-4o",
            "context_window": 200000,
        },
    )
    spec = llm_discovery.discover_model(cfg, "primary")
    assert spec.context_window == 200000
    assert spec.provider_details["context_window_source"] == "model_library"


def test_discover_model_uses_catalog_discovery_limits(monkeypatch):
    monkeypatch.setattr(
        llm_discovery,
        "capabilities_for_adapter",
        lambda provider, profile, base: base,
    )
    monkeypatch.setattr(
        llm_discovery,
        "resolve_model_capabilities",
        lambda **kwargs: {},
    )
    monkeypatch.setattr(
        llm_discovery,
        "load_model_catalog_state",
        lambda: {
            "schemaVersion": 2,
            "metadata": {},
            "providers": {
                "p1": {
                    "status": "reachable",
                    "catalogStale": False,
                    "models": {
                        "gpt-a": {
                            "upstreamId": "gpt-a",
                            "availability": "observed",
                            "limits": {"context_window": 456789},
                        }
                    },
                }
            },
        },
    )
    cfg = _config(
        model="gpt-a",
        provider_window=None,
        library_entry={
            "model_ref": "p1/gpt-a",
            "provider_id": "p1",
            "upstream_id": "gpt-a",
            "model": "gpt-a",
        },
    )
    spec = llm_discovery.discover_model(cfg, "primary")
    assert spec.context_window == 456789
    assert spec.provider_details["context_window_source"] == "provider_discovery"


def test_apply_discovered_context_windows_writes_without_override():
    public = {
        "llm": {
            "model_library": {
                "m1": {
                    "model": "gpt-a",
                    "provider": {"kind": "openai", "context_window": None},
                },
                "m2": {
                    "model": "gpt-b",
                    "context_window": 111111,
                    "provider": {"kind": "openai", "context_window": 111111},
                },
            }
        }
    }
    updated, written = apply_discovered_context_windows(
        public,
        [
            {"id": "gpt-a", "contextWindow": 250000},
            {"id": "gpt-b", "contextWindow": 999999},
        ],
        overwrite_existing=False,
    )
    assert "llm.model_library.m1.context_window" in written
    assert updated["llm"]["model_library"]["m1"]["context_window"] == 250000
    # Hand-edited entry must stay.
    assert updated["llm"]["model_library"]["m2"]["context_window"] == 111111
    assert not any(path.startswith("llm.model_library.m2.") for path in written)


def test_apply_discovered_context_windows_v2_pinned_models():
    public = {
        "llm": {
            "schema_version": 2,
            "providers": {
                "lab": {
                    "models": {
                        "gpt-a": {"upstream_id": "gpt-a", "label": "A"},
                        "gpt-b": {
                            "upstream_id": "gpt-b",
                            "label": "B",
                            "context_window": 12345,
                        },
                    }
                }
            },
        }
    }
    updated, written = apply_discovered_context_windows(
        public,
        [
            {"id": "gpt-a", "limits": {"context_window": 888000}},
            {"id": "gpt-b", "limits": {"context_window": 777000}},
        ],
        overwrite_existing=False,
    )
    assert updated["llm"]["providers"]["lab"]["models"]["gpt-a"]["context_window"] == 888000
    assert updated["llm"]["providers"]["lab"]["models"]["gpt-b"]["context_window"] == 12345
    assert any("gpt-a" in path for path in written)
    assert not any("gpt-b" in path for path in written)


def test_parse_response_fails_when_context_window_missing():
    from core.infrastructure.model_discovery import DiscoveryStatus, ModelDiscovery

    discovery = ModelDiscovery(api_base="http://localhost:8000/v1", model_name="x")
    result = discovery._parse_response({"data": [{"id": "x"}]}, "/v1/models")
    assert result.status == DiscoveryStatus.FAILED
    assert result.max_model_len == 0
    assert "禁止默认兜底" in (result.error_message or "")
