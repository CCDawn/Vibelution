from __future__ import annotations

from config.public_config import build_effective_config
from config.settings import normalize_public_config_dict


def _v2_config() -> dict:
    return {
        "llm": {
            "schema_version": 2,
            "providers": {
                "pixel_relay": {
                    "label": "Pixel Relay",
                    "service_class": "relay",
                    "vendor": "multi_model",
                    "driver": "openai",
                    "base_url": "https://relay.example/v1",
                    "auth_kind": "api_key",
                    "credential_ref": "env:VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY",
                    "requires_credential": True,
                    "protocols": {"default": "responses", "allowed": ["responses", "chat_completions"]},
                    "discovery": {"mode": "auto", "adapter": "openai_compatible", "cache_ttl_seconds": 3600},
                    "models": {
                        "gpt-5.6-luna": {
                            "upstream_id": "gpt-5.6-luna",
                            "label": "GPT-5.6 Luna",
                            "enabled": True,
                            "defaults": {"max_output_tokens": 32000, "timeout": 120},
                        }
                    },
                }
            },
            "profiles": {
                "primary": {
                    "model_ref": "pixel_relay/gpt-5.6-luna",
                    "overrides": {"temperature": 0.4},
                }
            },
        }
    }


def test_v2_projection_keeps_one_provider_and_flattens_only_runtime_models() -> None:
    normalized = normalize_public_config_dict(_v2_config())
    assert set(normalized["llm"]["providers"]) == {"pixel_relay"}
    assert set(normalized["llm"]["model_library"]) == {"pixel_relay/gpt-5.6-luna"}
    assert normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]["model"] == "gpt-5.6-luna"
    assert normalized["llm"]["profiles"]["primary"]["provider_id"] == "pixel_relay"
    assert normalized["llm"]["profiles"]["primary"]["temperature"] == 0.4
    assert normalized["llm"]["profiles"]["primary"]["max_output_tokens"] == 32000


def test_v2_effective_config_resolves_provider_credential_without_inline_copies(monkeypatch) -> None:
    monkeypatch.setenv("VIBELUTION_LLM_PROVIDER_PIXEL_RELAY_API_KEY", "secret")
    effective = build_effective_config(_v2_config())
    profile = effective.llm.get_profile("primary")
    provider = effective.llm.get_provider(profile.provider_id)
    assert effective.llm.schema_version == 2
    assert profile.model_ref == "pixel_relay/gpt-5.6-luna"
    assert profile.model == "gpt-5.6-luna"
    assert provider.provider_id == "pixel_relay"
    assert provider.resolve_api_key() == "secret"
    assert not any(provider_id.startswith("inline_") for provider_id in effective.llm.providers)


def test_v1_normalization_remains_read_only_and_compatible() -> None:
    legacy = {
        "llm": {
            "model_library": {
                "relay_model": {
                    "provider": {
                        "kind": "relay",
                        "base_url": "https://relay.example/v1",
                        "api_key_env": "RELAY_KEY",
                    },
                    "model": "gpt-5.6-luna",
                }
            },
            "profiles": {"primary": {"model_ref": "relay_model"}},
        }
    }
    normalized = normalize_public_config_dict(legacy)
    assert legacy["llm"]["model_library"]["relay_model"]["provider"]["kind"] == "relay"
    assert normalized["llm"]["profiles"]["primary"]["model"] == "gpt-5.6-luna"


def test_v2_projection_uses_cycle_safe_runtime_alias_resolver() -> None:
    chained = _v2_config()
    chained["llm"]["model_aliases"] = {
        "primary-model": "latest-model",
        "latest-model": "pixel_relay/gpt-5.6-luna",
    }
    chained["llm"]["profiles"]["primary"]["model_ref"] = "primary-model"

    normalized = normalize_public_config_dict(chained)

    assert normalized["llm"]["profiles"]["primary"]["model_ref"] == "pixel_relay/gpt-5.6-luna"

    cyclic = _v2_config()
    cyclic["llm"]["model_aliases"] = {"first": "second", "second": "first"}
    cyclic["llm"]["profiles"]["primary"]["model_ref"] = "first"

    try:
        normalize_public_config_dict(cyclic)
    except ValueError as exc:
        assert str(exc) == "cyclic model alias: first"
    else:  # pragma: no cover - assertion guard
        raise AssertionError("cyclic aliases must be rejected")
