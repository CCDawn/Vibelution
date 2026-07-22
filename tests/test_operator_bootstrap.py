"""Tests for template-derived operator config bootstrap."""

from __future__ import annotations

import tomllib

from config.operator_bootstrap import (
    build_default_llm_section,
    is_thin_local_only_starter,
    render_default_operator_config_text,
)
from config.paths import ensure_global_config_initialized
from config.public_config import build_effective_config


def test_bootstrap_includes_fixed_vendor_instances_without_inline_secrets() -> None:
    text = render_default_operator_config_text(
        include_unconfigured_providers=True,
        credential_env_overrides={
            "openai_main": "OPENAI_API_KEY",
            "deepseek_main": "DEEPSEEK_API_KEY",
            "relay_openai": "OPENAI_API_KEY",
        },
        env_reader=lambda _name: None,
    )
    payload = tomllib.loads(text)
    providers = payload["llm"]["providers"]
    assert "local_openai" in providers
    assert "openai_main" in providers
    assert "deepseek_main" in providers
    assert providers["openai_main"]["credential_ref"].startswith("env:")
    assert "api_key" not in providers["openai_main"]
    # Same base_url + credential_ref merge into one fingerprint group when needed.
    effective = build_effective_config(payload)
    assert effective.llm.schema_version == 2
    assert effective.llm.get_profile("primary").model_ref


def test_bootstrap_can_prefer_only_configured_credentials() -> None:
    def reader(name: str) -> str | None:
        return "secret" if name == "DEEPSEEK_API_KEY" else None

    llm = build_default_llm_section(
        env_reader=reader,
        include_unconfigured_providers=False,
        credential_env_overrides={"deepseek_main": "DEEPSEEK_API_KEY"},
    )
    assert "deepseek_main" in llm["providers"]
    assert "openai_main" not in llm["providers"]
    assert "local_openai" in llm["providers"]
    assert str(llm["profiles"]["primary"]["model_ref"]).startswith("deepseek_main/")


def test_thin_local_only_starter_is_upgraded_once(tmp_path) -> None:
    config_home = tmp_path / "config"
    config_home.mkdir()
    thin = """# Vibelution operator config
[llm]
schema_version = 2

[llm.providers.local_openai]
label = "Local OpenAI-compatible service"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:8000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.local_openai.protocols]
default = "chat_completions"
allowed = ["chat_completions"]

[llm.providers.local_openai.discovery]
mode = "auto"
adapter = "openai_compatible"
cache_ttl_seconds = 300

[llm.providers.local_openai.models.local-model]
upstream_id = "local-model"
label = "Local model"
enabled = true

[llm.profiles.primary]
model_ref = "local_openai/local-model"
"""
    config_path = config_home / "config.toml"
    config_path.write_text(thin, encoding="utf-8")
    assert is_thin_local_only_starter(tomllib.loads(thin))

    meta = ensure_global_config_initialized(config_path)
    upgraded = tomllib.loads(config_path.read_text(encoding="utf-8"))
    assert meta.get("upgradedThinStarter") is True
    assert meta.get("configSource") == "external_starter_upgrade"
    assert not is_thin_local_only_starter(upgraded)
    assert len(upgraded["llm"]["providers"]) >= 5
    backups = list((config_home / "backups").glob("operator-config-thin-starter-before-*.toml"))
    assert len(backups) == 1

    # Second call must not rewrite customized / already-upgraded config.
    before = config_path.read_text(encoding="utf-8")
    meta2 = ensure_global_config_initialized(config_path)
    assert config_path.read_text(encoding="utf-8") == before
    assert meta2.get("configSource") == "external_starter_upgrade"


def test_customized_local_only_config_is_never_replaced(tmp_path) -> None:
    config_home = tmp_path / "config"
    config_home.mkdir()
    custom = """# Keep this operator note.
[llm]
schema_version = 2

[llm.providers.local_openai]
label = "My local runtime"
service_class = "local_runtime"
vendor = "custom"
driver = "openai"
base_url = "http://127.0.0.1:9000/v1"
auth_kind = "none"
credential_ref = "none"
requires_credential = false

[llm.providers.local_openai.models.local-model]
upstream_id = "local-model"
label = "My model"
enabled = true

[llm.profiles.primary]
model_ref = "local_openai/local-model"
"""
    config_path = config_home / "config.toml"
    config_path.write_text(custom, encoding="utf-8")

    meta = ensure_global_config_initialized(config_path)

    assert config_path.read_text(encoding="utf-8") == custom
    assert meta.get("upgradedThinStarter") is False
    assert meta.get("configSource") == "existing"
    assert not list((config_home / "backups").glob("operator-config-thin-starter-before-*.toml"))
