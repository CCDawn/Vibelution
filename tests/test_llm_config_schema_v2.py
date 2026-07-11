from __future__ import annotations

import pytest

from config.models import AppConfig
from config.public_config import build_effective_config, load_public_config, public_config_hash
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


@pytest.mark.parametrize(
    ("scope", "field"),
    [
        ("provider", "api_key"),
        ("provider", "api_key_env"),
        ("model", "api_key"),
        ("model", "api_key_env"),
        ("model", "credential_ref"),
        ("defaults", "api_key"),
        ("defaults", "api_key_env"),
        ("defaults", "credential_ref"),
        ("profile", "api_key"),
        ("profile", "api_key_env"),
        ("profile", "credential_ref"),
        ("overrides", "api_key"),
        ("overrides", "api_key_env"),
        ("overrides", "credential_ref"),
    ],
)
def test_v2_rejects_credential_ownership_outside_provider_credential_ref(scope: str, field: str) -> None:
    public_config = _v2_config()
    provider = public_config["llm"]["providers"]["pixel_relay"]
    model = provider["models"]["gpt-5.6-luna"]
    profile = public_config["llm"]["profiles"]["primary"]
    owner = {
        "provider": provider,
        "model": model,
        "defaults": model["defaults"],
        "profile": profile,
        "overrides": profile["overrides"],
    }[scope]
    owner[field] = "secret-must-not-appear"

    with pytest.raises(ValueError) as exc_info:
        build_effective_config(public_config)

    message = str(exc_info.value)
    assert message == f"schema v2 credential ownership violation: {scope}.{field}"
    assert "secret-must-not-appear" not in message


def test_v2_public_config_boundary_rejects_inline_secret_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["api_key"] = "public-secret-must-not-appear"

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    message = str(exc_info.value)
    assert message == "schema v2 credential ownership violation: provider.api_key"
    assert "public-secret-must-not-appear" not in message


def test_v2_public_config_hash_rejects_input_model_library_without_echo() -> None:
    public_config = _v2_config()
    public_config["llm"]["model_library"] = {
        "secret-model-key": {"model": "legacy", "api_key": "hash-secret-must-not-appear"}
    }

    with pytest.raises(ValueError) as exc_info:
        public_config_hash(public_config)

    message = str(exc_info.value)
    assert message == "llm.model_library is not allowed in schema v2 input"
    assert "secret-model-key" not in message
    assert "hash-secret-must-not-appear" not in message


def test_v2_load_public_config_rejects_input_model_library_without_echo(tmp_path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """
[llm]
schema_version = 2

[llm.model_library.secret_model_key]
model = "legacy"
api_key = "load-secret-must-not-appear"
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError) as exc_info:
        load_public_config(config_path)

    message = str(exc_info.value)
    assert message == "llm.model_library is not allowed in schema v2 input"
    assert "secret_model_key" not in message
    assert "load-secret-must-not-appear" not in message


def test_v1_public_config_hash_still_accepts_legacy_model_library() -> None:
    legacy = {
        "llm": {
            "model_library": {
                "relay_model": {
                    "provider": {"kind": "relay", "base_url": "https://relay.example/v1"},
                    "model": "gpt-5.6-luna",
                }
            },
            "profiles": {"primary": {"model_ref": "relay_model"}},
        }
    }

    assert len(public_config_hash(legacy)) == 64


@pytest.mark.parametrize("scope", ["defaults", "overrides"])
def test_v2_rejects_runtime_fields_outside_explicit_allowlist(scope: str) -> None:
    public_config = _v2_config()
    provider = public_config["llm"]["providers"]["pixel_relay"]
    target = (
        provider["models"]["gpt-5.6-luna"]["defaults"]
        if scope == "defaults"
        else public_config["llm"]["profiles"]["primary"]["overrides"]
    )
    target["unapproved_runtime_flag"] = True

    with pytest.raises(ValueError) as exc_info:
        normalize_public_config_dict(public_config)

    assert str(exc_info.value) == f"unsupported schema v2 runtime field: {scope}.unapproved_runtime_flag"


@pytest.mark.parametrize("missing_section", ["providers", "profiles"])
def test_v2_empty_provider_or_profile_set_fails_closed_without_legacy_defaults(missing_section: str) -> None:
    public_config = _v2_config()
    public_config["llm"][missing_section] = {}

    with pytest.raises(ValueError, match=f"^llm.{missing_section} must not be empty in schema v2$"):
        normalize_public_config_dict(public_config)

    typed_input = {"llm": {"schema_version": 2, "providers": {}, "profiles": {}}}
    with pytest.raises(ValueError) as typed_exc_info:
        AppConfig.model_validate(typed_input)
    assert "llm.providers must not be empty in schema v2" in str(typed_exc_info.value)


@pytest.mark.parametrize(
    "upstream_id",
    [
        "  model with spaces  ",
        "模型/版本 β",
        "../models/private\\checkpoint",
    ],
)
def test_v2_projection_preserves_nonempty_upstream_id_exactly(upstream_id: str) -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["upstream_id"] = upstream_id

    normalized = normalize_public_config_dict(public_config)

    assert normalized["llm"]["model_library"]["pixel_relay/gpt-5.6-luna"]["model"] == upstream_id
    assert normalized["llm"]["profiles"]["primary"]["model"] == upstream_id


def test_v2_projection_rejects_whitespace_only_upstream_id() -> None:
    public_config = _v2_config()
    public_config["llm"]["providers"]["pixel_relay"]["models"]["gpt-5.6-luna"]["upstream_id"] = " \t\n "

    with pytest.raises(ValueError, match="^pinned model pixel_relay/gpt-5.6-luna requires upstream_id$"):
        normalize_public_config_dict(public_config)
